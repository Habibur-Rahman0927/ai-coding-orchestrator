"""Provider adapters. No provider response authorizes a local operation.

CLI transports retain upstream authentication/settings without changing them.
MiniMax uses the official independent HTTPS API and an environment key reference.
"""
from dataclasses import dataclass, field
import http.client
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import ssl
import socket
import subprocess
import threading
import time
import uuid

from .tools import supervised_command, tool_definitions
from .security import sensitive_content

MAX_RESPONSE = 4 * 1024 * 1024
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')

def validate_chat_options(provider, model=None, effort=None):
    if model is not None:
        validate_model(model)
    supported = EFFORTS if provider == 'codex' else EFFORTS[:-1] if provider == 'claude' else ()
    if effort is not None and effort not in supported:
        raise ValueError('Reasoning effort is not supported by this provider')
    return {'model': model, 'effort': effort}


MINIMAX_ENDPOINT = 'https://api.minimax.io/v1/chat/completions'


@dataclass
class ProviderRequest:
    project: Path
    prompt: str
    role: str = 'assistant'
    session_id: str = None
    model: str = None
    timeout: float = 300
    allowed_operations: tuple = ()
    history: list = field(default_factory=list)
    cancel_event: object = None
    max_output_tokens: int = 4096
    event_callback: object = None
    effort: str = None

    def validate(self):
        self.project = Path(self.project).resolve(strict=True)
        if not self.project.is_dir() or not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError('A project directory and nonempty prompt are required')
        if len(self.prompt.encode('utf-8')) > MAX_RESPONSE:
            raise ValueError('Prompt exceeds provider size limit')
        if not isinstance(self.timeout, (int, float)) or not 1 <= self.timeout <= 3600:
            raise ValueError('Provider timeout must be 1..3600 seconds')
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 32768:
            raise ValueError('Output token limit must be 1..32768')
        if self.session_id:
            self.session_id = str(uuid.UUID(self.session_id))
        if not isinstance(self.allowed_operations, (list, tuple, set, frozenset)) or not all(isinstance(item, str) for item in self.allowed_operations):
            raise ValueError('Allowed operations must be an explicit collection of names')
        if not isinstance(self.history, list):
            raise ValueError('History must be a list')
        if not isinstance(self.role, str) or len(self.role) > 200:
            raise ValueError('Invalid provider role')
        if self.event_callback is not None and not callable(self.event_callback):
            raise ValueError('Event callback must be callable')
        if self.model is not None:
            validate_model(self.model)
        if self.effort is not None and self.effort not in EFFORTS:
            raise ValueError('Unsupported reasoning effort')
        return self

    def cancelled(self):
        return bool(self.cancel_event and self.cancel_event.is_set())


def validate_model(model):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', model) or re.match(r'(?:sk[-_]|gh[pousr]_|github_pat_|AIza|AKIA|eyJ)', model, re.I):
        raise ValueError('An explicit valid model identifier is required')
    return model


def event(kind, **values):
    return dict(type=kind, **values)


def normalized_usage(value, provider_id=None):
    value = value if isinstance(value, dict) else {}
    result = {str(key): number for key, number in value.items()
              if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) and number >= 0}
    for destination, source in (('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')):
        if destination not in result and source in result: result[destination] = result[source]
    for parent, key, destination in (('prompt_tokens_details', 'cached_tokens', 'cached_input_tokens'),
                                     ('completion_tokens_details', 'reasoning_tokens', 'reasoning_tokens'),
                                     ('input_tokens_details', 'cached_tokens', 'cached_input_tokens'),
                                     ('output_tokens_details', 'reasoning_tokens', 'reasoning_tokens')):
        number = (value.get(parent) or {}).get(key) if isinstance(value.get(parent), dict) else None
        if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) and number >= 0: result[destination] = number
    if provider_id=='claude' and any(k in value for k in ('cache_read_input_tokens','cache_creation_input_tokens')):
        # Anthropic cache input fields are disjoint; input_tokens is uncached.
        uncached=result.pop('input_tokens',None)
        if uncached is not None: result['uncached_input_tokens']=uncached
        if 'cache_read_input_tokens' in result: result['cached_input_tokens']=result['cache_read_input_tokens']
        if uncached is not None and all(k in result for k in ('cache_read_input_tokens','cache_creation_input_tokens')):
            result['input_tokens']=uncached+result['cache_read_input_tokens']+result['cache_creation_input_tokens']
    return result


def classify_error(value):
    text = str(value).lower()
    for kind, terms in (('usage_limit', ('rate_limit', 'rate limit', 'usage limit', 'quota', '429', 'credit balance')),
                        ('authentication', ('unauthorized', 'authentication', 'invalid_api_key', '401', 'not logged in', 'credential')),
                        ('context_limit', ('context_length', 'context window', 'context limit', 'too many tokens')),
                        ('permission_denied', ('permission denied', 'forbidden', '403')),
                        ('network', ('connection', 'network', 'transport', '503', '502')),
                        ('incomplete', ('length', 'max_tokens', 'incomplete'))):
        if any(term in text for term in terms): return kind
    return 'provider_error'


def visible_activity(label, phase, detail='', output=''):
    # Only explicitly visible command output; never reasoning or raw provider payloads.
    if not isinstance(detail, str) or sensitive_content(detail):
        detail = '[Sensitive details withheld]'
    if not isinstance(output, str) or sensitive_content(output): output='[Sensitive output withheld]'
    return event('activity', label=label, phase=phase, detail=detail[:400], output=output[-12000:])


def normalize_cli(provider_id, data):
    """Normalize only documented visible text/session/result fields, not reasoning."""
    kind = data.get('type')
    if provider_id == 'codex':
        if kind in ('item.started', 'item.updated', 'item.completed'):
            item = data.get('item') or {}
            labels = {'command_execution': 'Command execution', 'file_change': 'File changes',
                      'mcp_tool_call': 'Tool activity', 'web_search': 'Web search'}
            if item.get('type') in labels:
                phase = 'failed' if item.get('status') == 'failed' else 'completed' if kind == 'item.completed' else 'running'
                detail = item.get('command', '') if item.get('type') == 'command_execution' else item.get('tool', '')
                if item['type']=='file_change': detail=', '.join(str(change.get('path','')) for change in item.get('changes',[]) if isinstance(change,dict))
                return [visible_activity(labels[item['type']], phase, detail, item.get('aggregated_output','') if item['type']=='command_execution' else '')]
        if kind == 'thread.started':
            return [event('session', session_id=str(uuid.UUID(data['thread_id'])))]
        if kind in ('item.updated', 'item.completed') and data.get('item', {}).get('type') == 'agent_message':
            return [event('text', text=data['item'].get('text', ''), message_id=data['item'].get('id','message'), snapshot=True)]
        if kind == 'turn.completed':
            return [event('usage', usage=normalized_usage(data.get('usage'),provider_id)), event('completed')]
        if kind in ('turn.failed', 'error'):
            return [event('error', error='Provider reported a failed turn', error_kind=classify_error(data.get('error') or data.get('subtype') or data.get('result')))]
    else:
        result = []
        if data.get('session_id'):
            result.append(event('session', session_id=str(uuid.UUID(data['session_id']))))
        if kind == 'stream_event':
            delta = (data.get('event') or {}).get('delta') or {}
            if delta.get('type') == 'text_delta' and isinstance(delta.get('text'), str):
                result.append(event('text', text=delta['text'], partial=True))
        if kind == 'assistant':
            for block in data.get('message', {}).get('content', []):
                if block.get('type') == 'tool_use':
                    result.append(visible_activity('Tool request', 'running', block.get('name', '')))
                if block.get('type') == 'text':
                    result.append(event('text', text=block.get('text', '')))
        if kind == 'result':
            if data.get('is_error') or data.get('subtype') not in (None, 'success'):
                result.append(event('error', error='Provider reported a failed turn', error_kind=classify_error(data.get('error') or data.get('subtype') or data.get('result'))))
            else:
                if isinstance(data.get('result'), str):
                    result.append(event('text', text=data['result'], final=True))
                result += [event('usage', usage=normalized_usage(data.get('usage'),provider_id)), event('completed')]
        return result
    return []


class CLIProvider:
    def __init__(self, provider_id, config=None):
        self.id = provider_id
        self.config = dict(config or {})

    def status(self):
        return {'id': self.id, 'available': bool(shutil.which(self.id)), 'installed': bool(shutil.which(self.id)), 'configured': bool(shutil.which(self.id)), 'authentication': 'unknown', 'connection_status': 'authentication_unknown' if shutil.which(self.id) else 'not_installed', 'last_verified_at': None,
                'model': self.config.get('model'), 'capabilities': {
                    'exact_session_resume': True, 'streaming_events': True, 'token_limit': False,
                    'scoped_tools': False, 'native_agent_authorization_required': True,
                    'native_tools': self.id == 'codex', 'filesystem_secret_filtering': False},
                'limitation': 'Native CLI settings/authentication are upstream controlled; scoped-tool policy does not sandbox the CLI.'}

    def command(self, request):
        validate_chat_options(self.id, request.model, request.effort)
        if 'native_agent_access' not in request.allowed_operations:
            raise PermissionError('Native CLI access requires explicit native_agent_access approval')
        if self.id == 'codex':
            sandbox = 'workspace-write' if 'native_agent_write' in request.allowed_operations else 'read-only'
            argv = ['codex', 'exec']
            if request.session_id:
                argv += ['resume']
            argv += ['--json', '-c', 'approval_policy="never"', '-c', 'sandbox_mode=' + json.dumps(sandbox)]
            model = request.model or self.config.get('model')
            if model:
                argv += ['--model', model]
            if request.effort:
                argv += ['-c', 'model_reasoning_effort=' + json.dumps(request.effort)]
            if request.session_id:
                argv += [request.session_id]
            argv += ['--', request.prompt]
            return argv
        argv = ['claude', '-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
                '--safe-mode', '--restricted', '--tools', '', '--disallowedTools', '*',
                '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                '--permission-mode', 'plan', '--permission-prompts', 'none']
        model = request.model or self.config.get('model')
        if model:
            argv += ['--model', model]
        if request.effort:
            argv += ['--effort', request.effort]
        if request.session_id:
            argv += ['--resume', request.session_id]
        argv += ['--', request.prompt]
        return argv

    def execute(self, request):
        request.validate()
        if request.cancelled():
            yield event('cancelled')
            return
        command = self.command(request)
        process = subprocess.Popen(supervised_command(command, request.timeout), cwd=str(request.project),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        messages = queue.Queue(maxsize=64)
        stopped = threading.Event()

        def reader():
            try:
                while not stopped.is_set():
                    line = process.stdout.readline(MAX_RESPONSE + 1)
                    if not line:
                        break
                    while not stopped.is_set():
                        try:
                            messages.put(line, timeout=.1)
                            break
                        except queue.Full:
                            pass
            finally:
                while not stopped.is_set():
                    try:
                        messages.put(None, timeout=.1)
                        break
                    except queue.Full:
                        pass
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        deadline = time.monotonic() + request.timeout + 5
        total, completed, failed = 0, False, False
        current_session = request.session_id
        text_messages = {}
        partial_message = False
        try:
            while True:
                if request.cancelled():
                    yield event('cancelled')
                    return
                if time.monotonic() >= deadline:
                    yield event('timeout', error='Provider execution exceeded deadline')
                    return
                try:
                    line = messages.get(timeout=.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                total += len(line)
                if total > MAX_RESPONSE:
                    yield event('error', error='Provider output limit exceeded')
                    return
                try:
                    raw = json.loads(line)
                except (ValueError, UnicodeError):
                    continue  # Do not echo native diagnostics that may contain credentials.
                if not isinstance(raw, dict):
                    continue
                if raw.get('status') == 'EXECUTION_TIMEOUT':
                    yield event('timeout', error='Provider execution exceeded deadline')
                    return
                normalized = normalize_cli(self.id, raw)
                for item in normalized:
                    if item['type'] == 'text':
                        if self.id == 'codex' and item.get('snapshot'):
                            text_messages[item['message_id']] = item['text']
                            item = event('text', text='\n\n'.join(text_messages.values()), final=True)
                        elif self.id == 'claude':
                            if item.get('partial'): partial_message = True
                            elif raw.get('type') == 'assistant' and partial_message: continue
                    if item['type'] == 'session':
                        if current_session and current_session != item['session_id']:
                            yield event('error', error='Provider returned an unexpected session identifier')
                            return
                        current_session = item['session_id']
                    completed |= item['type'] == 'completed'
                    failed |= item['type'] == 'error'
                    # Completion is emitted only after the supervisor confirms exit.
                    if item['type'] != 'completed':
                        yield item
                if self.id == 'claude' and raw.get('type') == 'assistant': partial_message = False
            code = process.wait(timeout=15)
            if code == 0 and completed and not failed and current_session:
                yield event('completed')
            else:
                yield event('error', error='Provider did not finish a verified successful turn', exit_code=code)
        finally:
            stopped.set()
            if process.poll() is None:
                process.terminate()  # Supervisor performs owned tree cleanup; Windows Job closes atomically.
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    # Do not claim cleanup when the supervisor cannot confirm it.
                    raise RuntimeError('Provider cleanup could not be confirmed')
            process.stdout.close()
            thread.join(timeout=1)


class MiniMaxProvider:
    id = 'minimax'

    def __init__(self, config=None, connection_factory=None, credential_resolver=None, credential_status=None):
        self.config = dict(config or {})
        self.connection_factory = connection_factory or http.client.HTTPSConnection
        self.credential_resolver = credential_resolver
        self.credential_status = credential_status

    def status(self):
        mode = self.config.get('credential_mode', 'environment')
        configured = bool(self.config.get('model') and (self.config.get('api_key_env') or mode in ('os', 'session')))
        present = self.credential_status(self.id).get('configured', False) if self.credential_status else bool(os.environ.get(self.config.get('api_key_env', '')))
        return {'id': self.id, 'available': configured and present, 'configured': configured, 'installed': True, 'authentication': 'unknown', 'authentication_method': mode, 'connection_status': 'authentication_unknown' if configured and present else 'not_configured', 'last_verified_at': None,
                'model': self.config.get('model'), 'capabilities': {'exact_session_resume': False,
                    'local_transcript_sessions': True, 'streaming_events': True, 'token_limit': True,
                    'scoped_tools': True, 'native_tools': False, 'filesystem_secret_filtering': True},
                'limitation': 'API calls require explicit sharing/cost approval; cancellation cannot revoke a request already received by MiniMax.'}

    def execute(self, request):
        request.validate()
        validate_chat_options('minimax', request.model, request.effort)
        model = validate_model(request.model or self.config.get('model'))
        key_name = self.config.get('api_key_env')
        if self.config.get('credential_mode', 'environment') == 'environment' and (not isinstance(key_name, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', key_name)):
            raise ValueError('Configure an API key environment-variable name, not a key value')
        key = self.credential_resolver(self.id, self.config) if self.credential_resolver else os.environ.get(key_name or '')
        if not key:
            raise RuntimeError('Configured MiniMax credential environment variable is unavailable')
        if self.config.get('endpoint', MINIMAX_ENDPOINT) != MINIMAX_ENDPOINT:
            raise PermissionError('MiniMax endpoint is not allowlisted')
        if request.cancelled():
            yield event('cancelled')
            return
        if request.session_id and not request.history:
            raise ValueError('Resuming a MiniMax local session requires its saved transcript')
        session = request.session_id or str(uuid.uuid4())
        messages = list(request.history)
        if not messages:
            messages.append({'role': 'system', 'content': 'Perform the assigned role: ' + request.role + '. Request only explicitly provided tools. Never claim tool execution without results.'})
        if not all(isinstance(item, dict) and item.get('role') in ('system', 'user', 'assistant', 'tool') for item in messages):
            raise ValueError('Invalid MiniMax transcript')
        # During a tool loop the engine supplies the complete previous response
        # and tool results. A new prompt is appended only when it is not a tool continuation.
        if not messages or messages[-1].get('role') != 'tool':
            messages.append({'role': 'user', 'content': request.prompt})
        payload = {'model': model, 'messages': messages, 'stream': True,
                   'max_completion_tokens': request.max_output_tokens}
        definitions = tool_definitions(request.allowed_operations)
        if definitions:
            payload['tools'] = definitions
        body = json.dumps(payload).encode('utf-8')
        if len(body) > MAX_RESPONSE:
            raise ValueError('MiniMax transcript exceeds request limit')
        connection = self.connection_factory('api.minimax.io', timeout=min(request.timeout, 30),
                                             context=ssl.create_default_context())
        outcome = queue.Queue(maxsize=1)
        stop = threading.Event()
        transport_socket = [None]

        def publish(value):
            while not stop.is_set() and not request.cancelled():
                try:
                    outcome.put(value, timeout=.1)
                    return
                except queue.Full:
                    continue

        def perform():
            try:
                if request.cancelled() or stop.is_set():
                    publish(('error', 'MiniMax request cancelled before transmission'))
                    return
                connection.connect()
                transport_socket[0] = getattr(connection, 'sock', None)
                if request.cancelled() or stop.is_set():
                    publish(('error', 'MiniMax request cancelled before transmission'))
                    return
                connection.request('POST', '/v1/chat/completions', body=body,
                                   headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
                response = connection.getresponse()
                if response.status != 200:
                    # Redirects are never followed; credentials stay on the allowlisted origin.
                    publish(('error', 'MiniMax HTTP status ' + str(response.status)))
                    return
                if 'text/event-stream' in getattr(response, 'getheader', lambda name, default='': default)('Content-Type', ''):
                    message = {'role':'assistant', 'content':''}
                    calls, usage, finish, total = {}, {}, None, 0
                    while not stop.is_set() and not request.cancelled():
                        line = response.readline(MAX_RESPONSE + 1)
                        if not line: break
                        total += len(line)
                        if total > MAX_RESPONSE: raise ValueError('Stream exceeds response limit')
                        if not line.startswith(b'data:'): continue
                        data = line[5:].strip()
                        if data == b'[DONE]': break
                        part = json.loads(data)
                        if part.get('usage'): usage = part['usage']
                        for choice in part.get('choices', []):
                            delta = choice.get('delta') or {}
                            if isinstance(delta.get('content'), str):
                                message['content'] += delta['content']
                                publish(('event', event('text', text=delta['content'])))
                            if isinstance(delta.get('reasoning_content'), str):
                                message['reasoning_content'] = message.get('reasoning_content','') + delta['reasoning_content']
                            for fragment in delta.get('tool_calls') or []:
                                index = fragment.get('index')
                                if type(index) != int or not 0 <= index < 16: raise ValueError('Invalid tool index')
                                call = calls.setdefault(index, {'id':'','type':'function','function':{'name':'','arguments':''}})
                                if fragment.get('id'): call['id'] = fragment['id']
                                for field in ('name','arguments'):
                                    call['function'][field] += fragment.get('function',{}).get(field,'')
                            if choice.get('finish_reason'): finish = choice['finish_reason']
                    if calls: message['tool_calls'] = [calls[i] for i in sorted(calls)]
                    publish(('result', {'choices':[{'message':message,'finish_reason':finish}], 'usage':usage, '_streamed':True}))
                    return
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    publish(('error', 'MiniMax response exceeds size limit'))
                    return
                publish(('result', json.loads(raw)))
            except Exception:
                publish(('error', 'MiniMax transport or response failure'))
            finally:
                connection.close()
        worker = threading.Thread(target=perform, daemon=True)
        worker.start()
        deadline = time.monotonic() + request.timeout
        yield event('session', session_id=session, scope='local_transcript')
        try:
            while True:
                if request.cancelled():
                    yield event('cancelled')
                    return
                if time.monotonic() >= deadline:
                    yield event('timeout', error='MiniMax request exceeded deadline')
                    return
                try:
                    kind, response = outcome.get(timeout=.1)
                    if kind == 'event':
                        yield response
                        continue
                    break
                except queue.Empty:
                    pass
            if kind == 'error':
                yield event('error', error=response, error_kind=classify_error(response))
                return
            if not isinstance(response, dict) or not response.get('choices'):
                yield event('error', error='MiniMax response schema is invalid')
                return
            choice = response['choices'][0]
            message = choice.get('message')
            if not isinstance(message, dict) or message.get('role') != 'assistant':
                yield event('error', error='MiniMax assistant response is invalid')
                return
            # Internal replay event. Preserve the COMPLETE provider message, but
            # never display reasoning_content/reasoning_details as visible output.
            yield event('message', message=message)
            yield event('history', history=messages + [message])
            if isinstance(message.get('content'), str):
                yield event('text', text=message['content'], final=True)
            yield event('usage', usage=normalized_usage(response.get('usage')))
            calls = message.get('tool_calls') or []
            if not isinstance(calls, list) or not all(isinstance(call, dict) and isinstance(call.get('function'), dict) for call in calls):
                yield event('error', error='MiniMax tool-call schema is invalid')
                return
            if len(calls) > 16:
                yield event('error', error='MiniMax tool-call limit exceeded')
                return
            identifiers = [call.get('id') for call in calls]
            if any(not isinstance(value, str) or not value or len(value) > 200 for value in identifiers) or len(set(identifiers)) != len(identifiers):
                yield event('error', error='MiniMax tool-call identifiers are invalid')
                return
            declared = {definition['function']['name'] for definition in definitions}
            for call in calls:
                function = call.get('function', {})
                arguments = json.loads(function.get('arguments', '{}'))
                if not isinstance(arguments, dict) or not isinstance(call.get('id'), str) or function.get('name') not in declared:
                    yield event('error', error='MiniMax requested an unauthorized or invalid tool')
                    return
                yield event('tool_call', tool_call={'id': call['id'], 'name': function['name'], 'arguments': arguments})
            if calls:
                yield event('tool_calls')
            elif choice.get('finish_reason') == 'stop':
                yield event('completed')
            else:
                yield event('error', error='MiniMax response stopped before completion', error_kind='incomplete' if choice.get('finish_reason') == 'length' else 'provider_error')
        finally:
            stop.set()
            sock = transport_socket[0] or getattr(connection, 'sock', None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()


class ProviderRegistry:
    def __init__(self, config=None, providers=None, credential_resolver=None, credential_status=None):
        self.credential_resolver = credential_resolver
        self.credential_status = credential_status
        self.config = {}
        for provider_id, value in (config or {}).items():
            self.configure(provider_id, value)
        self.providers = dict(providers or {})

    def configure(self, provider_id, config):
        if provider_id not in ('claude', 'codex', 'minimax') or not isinstance(config, dict):
            raise ValueError('Unknown provider or invalid configuration')
        allowed = {'model', 'api_key_env', 'endpoint', 'credential_mode'} if provider_id == 'minimax' else {'model'}
        if set(config) - allowed:
            raise ValueError('Provider configuration contains unsupported fields; never submit credentials')
        clean = dict(config)
        # Model/preferences forms must not silently switch an OS/session credential back to environment mode.
        if provider_id == 'minimax' and 'credential_mode' not in clean and provider_id in self.config:
            mode = self.config[provider_id].get('credential_mode')
            if mode is not None: clean['credential_mode'] = mode
        if 'model' in clean:
            validate_model(clean['model'])
        if 'credential_mode' in clean and clean['credential_mode'] not in ('environment', 'os', 'session'):
            raise ValueError('Unsupported credential mode')
        if 'api_key_env' in clean and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', str(clean['api_key_env'])):
            raise ValueError('Credential configuration requires an environment-variable name')
        if 'endpoint' in clean and clean['endpoint'] != MINIMAX_ENDPOINT:
            raise ValueError('Only the official allowlisted MiniMax endpoint is supported')
        self.config[provider_id] = clean
        return dict(clean)

    def get(self, provider_id):
        if provider_id in self.providers:
            return self.providers[provider_id]
        if provider_id == 'minimax':
            return MiniMaxProvider(self.config.get(provider_id), credential_resolver=self.credential_resolver, credential_status=self.credential_status)
        if provider_id in ('codex', 'claude'):
            return CLIProvider(provider_id, self.config.get(provider_id))
        raise ValueError('Unknown provider')

    def status(self):
        return [self.get(name).status() for name in ('claude', 'codex', 'minimax')]

    discover = status

    def probe(self, provider_id):
        result = self.get(provider_id).status()
        result['live_connection_tested'] = False
        return result

    def invoke(self, provider_id, request):
        if isinstance(request, dict):
            request = ProviderRequest(**request)
        result = {'status': 'failed', 'output': '', 'session_id': request.session_id,
                  'usage': {}, 'tool_calls': [], 'events': [], 'message': None, 'history': [], 'error': None, 'error_kind': None}
        try:
            for item in self.get(provider_id).execute(request):
                if sensitive_content(item):
                    raise ValueError('Recognizable sensitive provider event refused')
                kind = item.get('type')
                if kind == 'history':
                    result['history'] = item['history']  # Internal-only transcript data.
                    continue
                if kind == 'message':
                    result['message'] = item['message']  # Internal-only transcript data.
                    continue
                # Validate the assembled text before exposing this fragment to
                # browser telemetry; individually harmless fragments may form a key.
                if kind == 'text':
                    combined = item['text'] if item.get('final') else result['output'] + item['text']
                    if sensitive_content(combined):
                        result.update(output='', events=[], history=[], message=None, tool_calls=[])
                        raise ValueError('Recognizable sensitive provider output refused')
                    result['output'] = combined
                result['events'].append(item)
                if request.event_callback and kind in ('text', 'session', 'usage', 'tool_call', 'completed', 'cancelled', 'timeout', 'error', 'activity'):
                    try:
                        request.event_callback(dict(item))
                    except Exception:
                        pass  # UI telemetry failure cannot change provider authority or turn outcome.
                if kind == 'session':
                    result['session_id'] = item['session_id']
                elif kind == 'usage':
                    result['usage'].update(item['usage'])
                elif kind == 'tool_call':
                    result['tool_calls'].append(item['tool_call'])
                elif kind in ('completed', 'cancelled', 'timeout', 'tool_calls'):
                    result['status'] = kind
                    if kind in ('timeout', 'cancelled'): result['error_kind'] = kind
                elif kind == 'error':
                    result['status'], result['error'] = 'failed', item.get('error', 'Provider failed')
                    if result['error_kind'] in (None, 'provider_error'):
                        result['error_kind'] = item.get('error_kind') or classify_error(result['error'])
        except (PermissionError, ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError) as error:
            category = classify_error(error)
            result['error_kind'] = 'permission_denied' if isinstance(error, PermissionError) else category if category != 'provider_error' else 'configuration'
            result['status'], result['error'] = 'failed', 'Provider configuration, authorization, transport, or response validation failed'
        return result
