"""Read configured Windows folder paths/ACL metadata; never enumerate contents."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def folder_metadata():
    from desktop.windows_backup_chooser import configured_folders, NativeSaveDialog, _release
    result={'configured':[str(path) for path in configured_folders()]}
    with NativeSaveDialog() as dialog:
        item=None
        try:
            item=dialog._item('shell:Downloads')
            result['shell_Downloads_filesystem_path']=dialog._item_path(item)
        except OSError as exc:
            result['shell_Downloads_error']=str(exc)
        finally:
            _release(item)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    args = parser.parse_args()
    from desktop.windows_backup_chooser import configured_folders
    from desktop.windows_files import owned
    from desktop.isolation import profile_paths, isolated_environment
    before = configured_folders()
    result = {'metadata_only': True, 'configured_before_isolation': [],
              'native_before_isolation':folder_metadata()}
    for path in before:
        row = {'path': str(path), 'exists': path.is_dir()}
        try:
            owned(path)
            row['publication_parent_acl'] = 'accepted'
        except (OSError, ValueError) as exc:
            row['publication_parent_acl'] = str(exc)
        result['configured_before_isolation'].append(row)
    paths = profile_paths(args.profile)
    environment = isolated_environment(paths)
    code = ('import json; from tests.webview2.backup_places_probe import folder_metadata; '
            'print(json.dumps(folder_metadata()))')
    child = subprocess.run([sys.executable, '-c', code], env=environment,
                           capture_output=True, text=True, check=True)
    result['resolved_after_isolation_fresh_process'] = json.loads(child.stdout)
    result['captured_places_retained'] = [str(path) for path in before]
    with (paths['root'] / 'backup-places-metadata.json').open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
