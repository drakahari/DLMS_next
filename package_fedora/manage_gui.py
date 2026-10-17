"""Native standalone manager. Mutations are explicit and never run on UI thread."""
import json
from pathlib import Path

from PySide6.QtCore import QThread,Signal,Qt
from PySide6.QtWidgets import (QApplication,QFileDialog,QInputDialog,QLabel,QMainWindow,
    QMessageBox,QPlainTextEdit,QProgressBar,QPushButton,QVBoxLayout,QWidget)
from . import installation as inst, manual_replace as m
from .manage import locations,apply_plan


class Job(QThread):
    result=Signal(object);error=Signal(str)
    def __init__(self,fn,parent=None):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.result.emit(self.fn())
        except Exception as exc:self.error.emit(str(exc))


class ManagementWindow(QMainWindow):
    def __init__(self,home):
        super().__init__();self.home=home;self.job=None;self.plan=None
        self.setWindowTitle('Install / Manage DLMS Desktop')
        body=QWidget(self);layout=QVBoxLayout(body);self.setCentralWidget(body)
        intro=QLabel('Fedora 44 x86_64 private candidate. Manual actions only. Close DLMS before maintenance. '
            'Persistent data, backups and recovery evidence are kept outside versioned payloads.',body)
        intro.setWordWrap(True);layout.addWidget(intro)
        self.preview=QPlainTextEdit(body);self.preview.setReadOnly(True);self.preview.setAccessibleName('Exact installation locations and operation preview')
        self.preview.setPlainText(json.dumps(locations(home),indent=2));layout.addWidget(self.preview)
        self.status=QLabel('Choose an operation. No installation has changed.',body);self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setAccessibleName('Installation operation status');layout.addWidget(self.status)
        self.progress=QProgressBar(body);self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        self.buttons={}
        for key,label in (('install','New installation'),('reinstall','Reinstall retained data'),('transition-pilot','Transition existing pilot'),('update','Manual update'),('resume','Resume verified staged update'),('uninstall','Uninstall application — keep data'),('reconcile','Reconcile interrupted operation')):
            b=QPushButton(label,body);b.setAutoDefault(False);b.setAccessibleName(label);b.clicked.connect(lambda checked=False,k=key:self.select(k));layout.addWidget(b);self.buttons[key]=b
        self.apply=QPushButton('Confirm this exact preview…',body);self.apply.setAutoDefault(False);self.apply.setEnabled(False);self.apply.clicked.connect(self.confirm);layout.addWidget(self.apply)
        self.resize(650,780)
        self.setStyleSheet('QPushButton {padding:9px;} QPushButton:focus {border:2px solid palette(highlight);} QLabel {font-size:14px;}')

    def _start(self,fn,success):
        if self.job is not None:return
        self.apply.setEnabled(False)
        for b in self.buttons.values():b.setEnabled(False)
        self.progress.show();self.status.setText('Working; changes are not complete until a committed result is shown. Closing is refused while this operation is active.')
        worker=Job(fn,self);self.job=worker
        worker.result.connect(success);worker.error.connect(self.failed);worker.finished.connect(self.finished);worker.start()

    def finished(self):
        self.job=None;self.progress.hide()
        for b in self.buttons.values():b.setEnabled(True)
        self.apply.setEnabled(self.plan is not None)

    def failed(self,message):
        self.plan=None;self.status.setText('Operation refused or stopped: '+message+'\nEvidence is retained. No success is claimed. Use Reconcile for an incomplete transaction.')
        QMessageBox.warning(self,'DLMS Desktop operation stopped',self.status.text())

    def select(self,kind):
        if self.job is not None:return
        self.plan=None;self.apply.setEnabled(False)
        if kind=='reconcile':
            try:inst._outside_payload(self.home)
            except ValueError as exc:self.failed(str(exc));return
            self._start(lambda:inst.reconcile(self.home) if (inst.state_root(self.home)/'active.json').exists() else m.reconcile(self.home),self.completed);return
        if kind=='uninstall':self._start(lambda:inst.uninstall_plan(self.home),self.review);return
        initiating=self.buttons[kind]
        if kind=='resume':
            operation,ok=QInputDialog.getText(self,'Resume staged operation','Exact operation ID from manual-stage receipt after reconciliation:')
            initiating.setFocus()
            if not ok:self.status.setText('Resume cancelled. Installation unchanged.');return
            self._start(lambda:inst.resume_plan(self.home,operation),self.review);return
        source,_=QFileDialog.getOpenFileName(self,'Choose Fedora candidate archive',str(Path.home()/'Documents'),'Candidate archive (*.tar.zst)')
        initiating.setFocus()
        if not source:self.status.setText('Selection cancelled. Installation unchanged.');return
        expected,ok=QInputDialog.getText(self,'Expected artifact checksum','Expected SHA-256 from a trusted source. Checksum agreement does not authenticate the publisher:')
        initiating.setFocus()
        if not ok:self.status.setText('Checksum entry cancelled. Installation unchanged.');return
        retained=None
        if kind=='reinstall':
            retained,ok=QInputDialog.getText(self,'Retained removal identity','Operation ID from the committed removal receipt:')
            if not ok:self.status.setText('Reinstall selection cancelled. Data unchanged.');initiating.setFocus();return
        def prepare():
            value=inst.prepare_archive(self.home,Path(source),expected.strip())
            return inst.install_plan(self.home,value,reinstall=retained) if kind in ('install','reinstall') else inst.update_plan(self.home,value,promote=kind=='transition-pilot')
        self._start(prepare,self.review)

    def review(self,plan):
        self.plan=plan;self.preview.setPlainText(json.dumps(plan,indent=2));self.status.setText('Validated preview ready. Confirm to begin; cancellation leaves application data unchanged.')

    def confirm(self):
        if self.job is not None or self.plan is None:return
        plan=self.plan
        if plan['kind']=='uninstall':
            typed,ok=QInputDialog.getText(self,'Remove application files — keep data','Type REMOVE APPLICATION FILES. Data is preserved; code/evidence quarantine is retained as shown in preview:')
            if not ok or typed!='REMOVE APPLICATION FILES':self.status.setText('Confirmation cancelled. Installation unchanged.');self.apply.setFocus();return
        elif QMessageBox.question(self,'Confirm DLMS Desktop destination',f"Apply {plan['kind']} for {plan['home']}?\nProfile pilot01 and data: {plan['data_preserved']}\nReview the exact paths and checksum above.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
            self.status.setText('Confirmation cancelled. Installation unchanged.');self.apply.setFocus();return
        self.plan=None;self._start(lambda:apply_plan(self.home,plan,plan['confirmation']),self.completed)

    def completed(self,result):
        self.plan=None;self.preview.setPlainText(json.dumps(result,indent=2));self.status.setText('Committed operation verified. Data is retained. No application was launched automatically.')

    def closeEvent(self,event):
        if self.job is not None:
            self.status.setText('Operation still running. Closing is refused; interruption is not a harmless cancel.');event.ignore();return
        event.accept()


def run(home):
    app=QApplication.instance() or QApplication([])
    window=ManagementWindow(home);window.show();return app.exec()
