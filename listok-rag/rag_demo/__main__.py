import argparse
import sys
from .config import json_text, PROFILE

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', newline='\n')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Local Listok document search and citation validation')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare-model', 'validate-docs', 'chunks', 'compare-chunking', 'index'):
        commands.add_parser(name)
    for name in ('retrieve', 'ask'):
        command = commands.add_parser(name)
        command.add_argument('--question', required=True)
        command.add_argument(, type=int, default=PROFILE['default_top_k'])
        command.add_argument('--output')
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
        elif args.command in ('chunks', 'compare-chunking'):
            from .model import load_tokenizer
            from .documents import save_chunks, compare_chunking
            tokenizer = load_tokenizer()
            if args.command == 'chunks':
                docs, chunks, excluded = save_chunks(tokenizer)
                result = {'document_count': len(docs), 'chunk_count': len(chunks),
                          'chunks_path': 'evidence/chunks.json', 'excluded': excluded}
            else:
                compare_chunking(tokenizer)
                result = {'comparison_path': 'evidence/chunking-comparison.json'}
        elif args.command == 'index':
            from .storage import index
            result = index()
        elif args.command == 'finalize':
            from .evidence import finalize
            result = finalize(args.retrieval, args.answer_file)
        else:
            from .storage import retrieve
            result = retrieve(args.question, args.top_k, args.output)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    sys.stdout.write(json_text(result))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
