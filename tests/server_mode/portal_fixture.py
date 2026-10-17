"""Private test-session portal; records only synthetic application's calls."""
import json,sys,time
from pathlib import Path
from PySide6.QtCore import QCoreApplication,QTimer
from PySide6.QtDBus import QDBusConnection,QDBusVirtualObject,QDBusMessage
out=Path(sys.argv[1]);app=QCoreApplication([]);connection=QDBusConnection.sessionBus()
class Portal(QDBusVirtualObject):
    def introspect(self,path):return '<node/>'
    def handleMessage(self,message,conn):
        row={'member':message.member(),'interface':message.interface(),'sender':message.service(),'args':[str(x) for x in message.arguments()],'at':time.monotonic()}
        with out.open('a') as f:f.write(json.dumps(row)+'\n')
        if message.interface()=='org.freedesktop.DBus.Properties' and message.member()=='Get':reply=message.createReply([2])
        elif message.interface()=='org.freedesktop.host.portal.Registry' and message.member()=='Register':reply=message.createReply([])
        else:reply=message.createErrorReply('org.freedesktop.DBus.Error.UnknownMethod','Synthetic portal supports only Registry and Screenshot version')
        conn.send(reply);return True
portal=Portal();assert connection.registerVirtualObject('/org/freedesktop/portal/desktop',portal)
assert connection.registerService('org.freedesktop.portal.Desktop')
Path(str(out)+'.ready').write_text('ready')
app.exec()
