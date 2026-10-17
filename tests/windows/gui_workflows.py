"""Source Qt native-action checks. Never normal-package physical evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import time
import uuid

from tests.gate1.qt_checks import QtChecks
from tests.settings.gui_native_roundtrip import facts
from desktop.isolation import AREA, PROJECT

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--profile",required=True)
    parser.add_argument("--case",choices=("import","import-reopen","remove","remove-interrupt"),required=True)
    parser.add_argument("--archive",type=Path);parser.add_argument("--oracle",type=Path)
    args=parser.parse_args();q=QtChecks(args.profile,automated=True)
    work=PROJECT/".gate1/windows-native";result={"case":args.case,"profile":args.profile,"instrumented_source_Qt":True}
    try:
        if args.case=="import":
            from PySide6.QtWidgets import QFileDialog,QMessageBox
            archive=args.archive.resolve(strict=True)
            before=hashlib.sha256(archive.read_bytes()).hexdigest()
            q.go("/settings/backup")
            deadline=time.monotonic()+15
            while (not q.window._settings_ready("backup") or not q.window.settings_buttons["backup"].isEnabled()) and time.monotonic()<deadline:q.delay(.05)
            assert q.window._settings_ready("backup") and q.window.settings_buttons["backup"].isEnabled()
            old_picker,old_question,old_warning=QFileDialog.getOpenFileName,QMessageBox.question,QMessageBox.warning
            warnings=[]
            try:
                QFileDialog.getOpenFileName=lambda *a,**kw:(str(archive),"DLMS backups (*.zip)")
                QMessageBox.question=lambda *a,**kw:QMessageBox.StandardButton.Yes
                QMessageBox.warning=lambda parent,title,message,*a,**kw:(warnings.append(str(message)) or QMessageBox.StandardButton.Ok)
                q.window.settings_buttons["backup"].click()
                assert q.window.import_in_progress or q.window.backup_selection_future is not None, q.window.statusBar().currentMessage()
                deadline=time.monotonic()+120
                while time.monotonic()<deadline:
                    q.delay(.1)
                    if (q.window.import_worker is None and not q.window.import_in_progress
                            and q.window.backup_selection_future is None):
                        receipts=list((q.paths["root"]/"imports").glob("*.json"))
                        if any(json.loads(p.read_text())["state"]=="completed" for p in receipts):break
                        if q.window.operation_feedback.message:
                            raise RuntimeError(q.window.operation_feedback.message)
                else:raise TimeoutError("Native import did not reach a completed receipt")
                q.wait("location.pathname==='/' && document.readyState==='complete'",30)
            finally:
                result["warnings"]=warnings
                QFileDialog.getOpenFileName,QMessageBox.question,QMessageBox.warning=old_picker,old_question,old_warning
            assert hashlib.sha256(archive.read_bytes()).hexdigest()==before
            expected=json.loads(args.oracle.read_text(encoding="utf-8"))
            actual=facts(q.paths["backend"])
            assert actual==expected,"Imported rows/assets differ"
            result.update(confirmed_source_sha256=before,rows_assets_equal=True)
        elif args.case=="import-reopen":
            assert facts(q.paths["backend"])==json.loads(args.oracle.read_text(encoding="utf-8"))
            result["same_records_after_separate_reopen"]=True
        elif args.case=="remove-interrupt":
            from desktop.removal import begin_intent
            marker=begin_intent(args.profile,uuid.uuid4().hex)
            (work/(args.profile+"-interrupted-intent.json")).write_text(json.dumps(marker,indent=2)+"\n")
            # Only this disposable source harness is killed. The outer job must
            # remove its backend/helpers and leave the exact tombstone intact.
            os._exit(75)
        else:
            assert q.window.begin_removal(confirmed=True)
            deadline=time.monotonic()+200
            while time.monotonic()<deadline and not q.window._close_complete:
                if q.window.failed_reason:raise RuntimeError(q.window.failed_reason)
                q.delay(.1)
            marker=json.loads((AREA/"removed"/(args.profile+".json")).read_text())
            assert marker["phase"]=="removed",marker
            assert not q.paths["root"].exists()
            result.update(verified_removal=True,worker_exit=q.window.removal_worker.returncode)
        result["passed"]=True
    finally:
        if q.window.isVisible():q.close()
        (work/(args.profile+"-"+args.case+".json")).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))

if __name__=="__main__":main()
