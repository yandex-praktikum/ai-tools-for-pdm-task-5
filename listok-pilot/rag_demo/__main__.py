import argparse
import sys
from .config import json_text, PROFILE

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', newline='\n')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Local Listok document search and citation validation')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare-model', 'validate-docs', 'chunks', 'index'):
        commands.add_parser(name)
    for name in ('retrieve', 'ask'):
        command = commands.add_parser(name)
        command.add_argument('--question', required=True)
        command.add_argument('--top-k', type=int, default=PROFILE['default_top_k'])
        command.add_argument('--output')
        command.add_argument('--role', choices=('customer', 'support', 'manager'), default='customer')
        command.add_argument('--no-cache', action='store_true',
                             help='Run a fresh vector search without using or filling the query cache')
    command = commands.add_parser('cache')
    actions = command.add_subparsers(dest='cache_action', required=True)
    actions.add_parser('status')
    actions.add_parser('clear')
    command = commands.add_parser('policy')
    actions = command.add_subparsers(dest='policy_action', required=True)
    action = actions.add_parser('show')
    action.add_argument('--version', choices=('v1', 'v2'))
    action = actions.add_parser('use')
    action.add_argument('--version', required=True, choices=('v1', 'v2'))
    command = commands.add_parser('finalize')
    command.add_argument('--retrieval', required=True)
    command.add_argument('--answer-file', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare-model':
            from .model import prepare_model
            result = prepare_model()
        elif args.command == 'validate-docs':
            from .documents import load_documents
            docs, excluded = load_documents()
            result = {'status': 'documents_valid', 'document_count': len(docs),
                      'included_ids': [d.metadata['id'] for d in docs], 'excluded': excluded}
        elif args.command == 'policy':
            from .policy import snapshot, use
            result = use(args.version) if args.policy_action == 'use' else {'status': 'policy', 'policy': snapshot(args.version)}
        elif args.command == 'cache':
            from .query_cache import status, clear
            result = status() if args.cache_action == 'status' else clear()
        elif args.command == 'chunks':
            from .model import load_tokenizer
            from .documents import save_chunks
            tokenizer = load_tokenizer()
            docs, chunks, excluded = save_chunks(tokenizer)
            result = {'document_count': len(docs), 'chunk_count': len(chunks),
                      'chunks_path': 'evidence/chunks.json', 'excluded': excluded}
        elif args.command == 'index':
            from .storage import index
            result = index()
        elif args.command == 'finalize':
            from .evidence import finalize
            result = finalize(args.retrieval, args.answer_file)
        else:
            from .storage import retrieve
            result = retrieve(args.question, args.top_k, args.output, args.role,
                              use_cache=not args.no_cache)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    sys.stdout.write(json_text(result))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
