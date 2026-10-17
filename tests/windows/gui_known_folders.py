"""Read-only Windows shell-folder resolution in a disposable scoped process."""
import argparse
import json
import os
from pathlib import Path

from desktop.isolation import profile_paths,isolated_environment,PROJECT

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    paths=profile_paths(a.profile)
    env=isolated_environment(paths);os.environ.clear();os.environ.update(env)
    from PySide6.QtCore import QStandardPaths
    result={}
    for name in ('HomeLocation','DesktopLocation','DocumentsLocation','DownloadLocation'):
        value=Path(QStandardPaths.writableLocation(getattr(QStandardPaths.StandardLocation,name)))
        result[name]={'path':str(value),'exists':value.is_dir(),'inside_scoped_home':value.is_relative_to(paths['home'])}
    output=PROJECT/'.gate1/windows-native/chooser-blanking-01'/f'{a.profile}-known-folders.json'
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
