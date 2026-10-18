"""Serialized native export publication; browser sees only private staging."""
from concurrent.futures import ThreadPoolExecutor
import json,os
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,Qt
from PySide6.QtWidgets import QFileDialog,QMessageBox
from .profile_state import atomic_json
from .isolation import AREA,PROJECT,FROZEN
from .browser_lifetime import browser_dialog
from . import export_output


def scope(owner):
    return ({'mode':'local','uuid':owner.manifest['uuid'],'epoch':owner.manifest['epoch']}
            if owner.mode=='local' else {'mode':'server','server':owner.mode_config['server']['id'],'origin':owner.mode_config['server']['origin']})

def root(owner):return owner.paths['root'] if owner.mode=='local' else owner.server_paths['root']
def forbidden():return (AREA,PROJECT if FROZEN else PROJECT/'desktop')

def directory_allowed(path):
    path=Path(path)
    if any(path.is_relative_to(p) for p in forbidden()):raise ValueError('Choose an ordinary folder outside managed application storage')
    with export_output.parent_fd(path/'.dlms-export-folder-check'):pass
    return path

def initial(owner,kind='export'):
    if kind not in {'export','upload'}:raise ValueError('Invalid dialog purpose')
    preference=root(owner)/(kind+'-folder.json')
    try:
        if preference.is_symlink() or preference.stat().st_size>8192:raise ValueError('Unsafe saved folder')
        data=json.loads(preference.read_text())
        if set(data)!={'version','scope','directory'} or data['version']!=1 or data['scope']!=scope(owner):raise ValueError('Stale saved folder')
        return directory_allowed(data['directory']),''
    except FileNotFoundError:return owner._documents_folder(),''
    except (OSError,ValueError,TypeError):return owner._documents_folder(),'The previous selected folder is unavailable or unsafe. Choose another folder.'


def remember(owner,directory,kind='export'):
    if kind not in {'export','upload'}:raise ValueError('Invalid dialog purpose')
    directory=directory_allowed(directory)
    atomic_json(root(owner)/(kind+'-folder.json'),{'version':1,'scope':scope(owner),'directory':str(directory)})


def context(owner):
    page=owner.view.page()
    return (page,owner._browser_generation,scope(owner),root(owner),bytes(owner.view.url().toEncoded()),page.document_generation)


def current(owner,captured):
    return (not owner._closing and owner._retiring_browser is None and owner.view is not None
        and owner.view.page() is captured[0] and owner._browser_generation==captured[1]
        and scope(owner)==captured[2] and bytes(owner.view.url().toEncoded())==captured[4]
        and captured[0].document_generation==captured[5])


def begin(owner,record,*,captured):
    if not hasattr(owner,'_native_exports'):owner._native_exports=ExportQueue(owner)
    record['native_export']=True
    if record.get('marked_blob_url'):
        from .marked_exports import authorize
        def decided(permitted):
            if permitted:
                owner._native_exports.enqueue(record,captured)
            else:
                record['state']='refused'
                from .marked_exports import report
                report(owner,record,captured,'refused')
                if current(owner,captured):
                    owner._feedback(record['feedback_ticket'],
                        'Anki download not saved: use Export to Anki or its Download Anki package link in this page. Private bytes retained; no destination changed.','error')
        authorize(owner,record,captured,decided)
    else:
        owner._native_exports.enqueue(record,captured)


class ExportQueue(QObject):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.queue=[];self.active=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='dlms-export')
        self.timer=QTimer(self);self.timer.setInterval(40);self.timer.timeout.connect(self.poll)
    def enqueue(self,record,captured):
        owner=self.owner
        self.queue.append((record,*captured))
        if self.active is None:QTimer.singleShot(0,self.next)
    def valid(self,item):
        return current(self.owner,item[1:])
    def next(self):
        if self.active is not None or not self.queue:return
        owner=self.owner
        if owner._browser_dialog_depth or getattr(owner,'_browser_operation_depth',0):
            QTimer.singleShot(60,self.next);return
        item=self.queue.pop(0);self.active=item;record=item[0]
        try:
            if not self.valid(item):raise ValueError('The export page or dataset changed; private download retained for inspection')
            folder,warning=initial(owner)
            if warning:owner._feedback(record['feedback_ticket'],warning,'warning')
            focus=owner.focusWidget()
            with browser_dialog(owner):
                chosen,_=QFileDialog.getSaveFileName(owner,
                    f"Save {'Local '+owner.profile_name if owner.mode=='local' else 'Server '+owner.mode_config['server']['origin']} export",
                    str(folder/Path(record['path']).name),'All files (*)',options=QFileDialog.Option.DontConfirmOverwrite)
            if not self.valid(item):raise ValueError('Page or mode changed during Save As; no visible file was published')
            if focus is not None:focus.setFocus(Qt.FocusReason.OtherFocusReason)
            if not chosen:
                record['state']='cancelled';owner._feedback(record['feedback_ticket'],'Export save canceled; private download retained. No destination was changed.')
                from .marked_exports import report
                report(owner,record,item[1:],'cancelled')
                self.finish();return
            selection=export_output.select(Path(chosen),forbidden=forbidden())
            self.future=self.pool.submit(export_output.publish,Path(record['path']),selection)
            owner._feedback(record['feedback_ticket'],'Publishing the completed export to your selected folder…')
            self.timer.start()
        except (OSError,ValueError) as exc:
            record['state']='failed'
            from .marked_exports import report
            report(owner,record,item[1:],'refused')
            if self.valid(item):
                owner._feedback(record['feedback_ticket'],f'Export not saved: {exc}. Private download retained.','error')
                with browser_dialog(owner):
                    prompt=QMessageBox(owner);prompt.setTextFormat(Qt.TextFormat.PlainText);prompt.setWindowTitle('Export not saved');prompt.setText(str(exc));prompt.exec()
            self.finish()
    def poll(self):
        if self.active is None or not self.future.done():return
        self.timer.stop();item=self.active;record=item[0];owner=self.owner
        try:
            saved=self.future.result();record['state']='completed';record['published_path']=saved['path'];record['sha256']=saved['sha256']
            if item[3]['mode']=='local': owner.downloaded_files.append(Path(saved['path']))
            # Preference failure is separate: completed output remains completed.
            try:
                directory=directory_allowed(Path(saved['path']).parent)
                atomic_json(item[4]/'export-folder.json',{'version':1,'scope':item[3],'directory':str(directory)})
            except (OSError,ValueError) as exc:
                if self.valid(item):owner._feedback(record['feedback_ticket'],f"Export saved: {saved['path']}. Folder could not be remembered: {exc}",'warning')
            else:
                if self.valid(item):owner._feedback(record['feedback_ticket'],f"Export saved: {saved['path']}",'success')
            from .marked_exports import report
            report(owner,record,item[1:],'completed')
        except Exception as exc:
            record['state']='failed'
            from .marked_exports import report
            report(owner,record,item[1:],'unconfirmed')
            if self.valid(item):owner._feedback(record['feedback_ticket'],f'Export publication unconfirmed: {exc}. Inspect the selected folder and retained private download before retrying.','error')
        self.finish()
    def finish(self):
        self.active=None
        if self.queue:QTimer.singleShot(0,self.next)
