"""V5 CLI. Explicitly separate database and commands from V4 project history."""
import argparse
import json
from pathlib import Path
import sys
import ccx_platform as native
from .store import Store


def parser():
    p=argparse.ArgumentParser(prog='orchestrator workspace')
    p.add_argument('--database',type=Path,default=native.data_root()/'workspace-v5/workspace.sqlite3')
    subs=p.add_subparsers(dest='command',required=True)
    subs.add_parser('projects')
    reg=subs.add_parser('register');reg.add_argument('path',type=Path);reg.add_argument('--exclude',action='append',default=[])
    machine=subs.add_parser('machine');machine.add_argument('--refresh',action='store_true')
    index=subs.add_parser('index');index.add_argument('project')
    search=subs.add_parser('search');search.add_argument('project');search.add_argument('query');search.add_argument('--scope')
    context=subs.add_parser('context');context.add_argument('project');context.add_argument('query');context.add_argument('--budget',type=int,default=2000);context.add_argument('--critical',action='append',default=[])
    memory=subs.add_parser('remember');memory.add_argument('project');memory.add_argument('title');memory.add_argument('body');memory.add_argument('--scope',default='project');memory.add_argument('--kind',default='user_instruction')
    export=subs.add_parser('export');export.add_argument('project')
    delete=subs.add_parser('forget');delete.add_argument('project');delete.add_argument('id')
    backup=subs.add_parser('backup');backup.add_argument('destination',type=Path)
    bench=subs.add_parser('benchmark');bench.add_argument('project');bench.add_argument('queries',nargs='+');bench.add_argument('--budget',type=int,default=2000)
    legacy=subs.add_parser('import-v4');legacy.add_argument('project');legacy.add_argument('directory',type=Path);legacy.add_argument('--yes',action='store_true')
    subs.add_parser('providers')
    for command in ('dashboard','start','_serve','restart'):
        dashboard=subs.add_parser(command);dashboard.add_argument('--port',type=int,default=8765)
        dashboard.add_argument('--no-browser',action='store_true')
        dashboard.add_argument('--background',action='store_true',help='Explicitly start a detached process; does not register an OS service')
    for command in ('stop','status','doctor'):subs.add_parser(command)
    mcp=subs.add_parser('mcp');mcp.add_argument('--project',required=True)
    wf=subs.add_parser('workflow');w=wf.add_subparsers(dest='action',required=True)
    create=w.add_parser('create');create.add_argument('project');create.add_argument('objective');create.add_argument('--criterion',action='append',required=True);create.add_argument('--executor',default='codex');create.add_argument('--reviewer',default='claude');create.add_argument('--orchestrator',default='codex')
    create.add_argument('--budgets',default='{}',help='JSON object of explicit workflow budget limits')
    create.add_argument('--model-overrides',default='{}',help='JSON role-to-model mapping for this workflow only')
    create.add_argument('--execution-policy',choices=('standard','single_task'),default='standard')
    create.add_argument('--context-mode',choices=('retrieved','full_index'),default='retrieved',help='full_index is an explicit benchmark control')
    w.add_parser('list')
    for name in ('status','run','pause','resume','cancel','checkpoints','usage','context','results'):
        cmd=w.add_parser(name);cmd.add_argument('id')
    add=w.add_parser('task');add.add_argument('id');add.add_argument('title');add.add_argument('--description',default='')
    approval=w.add_parser('approve');approval.add_argument('id');approval.add_argument('kind');approval.add_argument('scope',help='JSON authorization scope');approval.add_argument('--yes',action='store_true')
    delegate=w.add_parser('delegate');delegate.add_argument('task');delegate.add_argument('provider');delegate.add_argument('--from-provider')
    failover=w.add_parser('failover');failover.add_argument('task');failover.add_argument('provider');failover.add_argument('--yes',action='store_true')
    revoke=w.add_parser('revoke');revoke.add_argument('id');revoke.add_argument('approval');revoke.add_argument('--yes',action='store_true')
    compare=subs.add_parser('compare-usage');compare.add_argument('baseline');compare.add_argument('optimized')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        store=Store(args.database)
        if args.command=='projects': result=store.projects()
        elif args.command=='register': result=store.register(args.path,args.exclude)
        elif args.command=='machine': result=store.machine(args.refresh)
        elif args.command=='index': result=store.index(args.project)
        elif args.command=='search': result=store.search(args.project,args.query,args.scope)
        elif args.command=='context': result=store.context(args.project,args.query,args.budget,args.critical)
        elif args.command=='remember': result=store.add_memory(args.project,args.scope,args.title,args.body,kind=args.kind)
        elif args.command=='export': result=store.export_memory(args.project)
        elif args.command=='forget': result=store.delete_memory(args.id,args.project)
        elif args.command=='backup': result=store.backup(args.destination)
        elif args.command=='benchmark':
            from .benchmark import benchmark
            result=benchmark(store,args.project,args.queries,args.budget)
        elif args.command=='compare-usage':
            from .benchmark import compare_workflows
            result=compare_workflows(store,args.baseline,args.optimized)
        elif args.command in ('dashboard','start','_serve','restart','stop','status'):
            from . import service
            if args.command=='stop':result=service.stop(store)
            elif args.command=='status':result=service.status(store)
            elif args.command=='_serve':result=service.run(store,args.port,browser=False)
            else:
                if args.command=='restart':
                    service.stop(store)
                    if service.status(store).get('running'):raise RuntimeError('Previous service has not stopped')
                result=service.start(store,args.port,args.background,not args.no_browser)
        elif args.command=='doctor':
            from .onboarding import doctor
            from .settings import registry_for
            from .workflows import WorkflowEngine
            result=doctor(store,registry_for(store),WorkflowEngine(store))
        elif args.command=='mcp':
            from .mcp import serve
            serve(store,args.project);return 0
        elif args.command=='import-v4':
            if not args.yes: raise PermissionError('Explicit --yes required for selected legacy knowledge import')
            from .migration import import_v4
            result=import_v4(store,args.project,args.directory)
        elif args.command=='providers':
            from .settings import registry_for
            result=registry_for(store).discover()
        elif args.command=='workflow':
            from .workflows import WorkflowEngine
            engine=WorkflowEngine(store)
            if args.action=='create':
                budgets=json.loads(args.budgets)
                if not isinstance(budgets,dict):raise ValueError('--budgets must be a JSON object')
                result=engine.create(args.project,args.objective,args.criterion,providers={'planner':args.orchestrator,'executor':args.executor,'reviewer':args.reviewer},budgets=budgets,
                    model_overrides=json.loads(args.model_overrides),execution_policy=args.execution_policy,context_mode=args.context_mode)
            elif args.action=='list': result=engine.list()
            elif args.action=='task': result=engine.create_task(args.id,args.title,args.description)
            elif args.action=='run':
                from .settings import registry_for
                result=engine.run(args.id,registry_for(store))
            elif args.action=='approve':
                if not args.yes: raise PermissionError('Review exact scope and add --yes to authorize')
                result=engine.approve(args.id,args.kind,json.loads(args.scope),actor='user')
            elif args.action=='delegate':result=engine.delegate(args.task,args.provider,args.from_provider)
            elif args.action=='usage':
                from .benchmark import usage_report
                result=usage_report(store,args.id)
            elif args.action=='context':result=engine.context_report(args.id)
            elif args.action=='results':result=engine.action_results(args.id)
            elif args.action=='failover':
                if not args.yes:raise PermissionError('Review the provider transition and add --yes; a matching failover approval is also required')
                result=engine.failover(args.task,args.provider,actor='user')
            elif args.action=='revoke':
                if not args.yes:raise PermissionError('Add --yes to revoke the selected approval')
                result=engine.revoke(args.id,args.approval,actor='user')
            else: result=getattr(engine,args.action)(args.id)
        else: raise ValueError('Unknown command')
        print(json.dumps(result,indent=2,ensure_ascii=True));return 0
    except (OSError,ValueError,KeyError,RuntimeError) as error:
        print('Workspace operation refused: '+str(error),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
