"""Private bus fake using existing Fedora dbus-python/GLib test tools.

Run with /usr/bin/python3, never registered on the real graphical session bus.
No browser is opened. Not a runtime/build dependency or shipped module.
"""
import json,sys,os
from pathlib import Path
import dbus,dbus.service,dbus.mainloop.glib
from gi.repository import GLib
# Refuse accidental registration on the real desktop bus. All supported test
# buses explicitly use a project-local UNIX path and no activation directories.
assert 'unix:path='+str(Path(__file__).resolve().parents[2]/'.gate1')+'/' in os.environ.get('DBUS_SESSION_BUS_ADDRESS',''), 'A private project-local bus is required'
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus=dbus.SessionBus();output=Path(sys.argv[1]);mode=sys.argv[2]
name=dbus.service.BusName('org.freedesktop.portal.Desktop',bus)
PATH='/org/freedesktop/portal/desktop'
def record(member,path,args):
 with output.open('a') as f:f.write(json.dumps({'member':member,'path':path,'args':args},default=str)+'\n')
class Request(dbus.service.Object):
 @dbus.service.method('org.freedesktop.portal.Request',in_signature='',out_signature='')
 def Close(self):record('Close',self._object_path,[])
 @dbus.service.signal('org.freedesktop.portal.Request',signature='ua{sv}')
 def Response(self,code,results):pass
class Portal(dbus.service.Object):
 @dbus.service.method('org.freedesktop.DBus.Properties',in_signature='ss',out_signature='v')
 def Get(self,interface,prop):return dbus.UInt32(5)
 @dbus.service.method('org.freedesktop.portal.OpenURI',in_signature='ssa{sv}',out_signature='o',sender_keyword='sender')
 def OpenURI(self,parent,uri,options,sender):
  record('OpenURI',PATH,[str(parent),str(uri),{str(k):str(v) for k,v in options.items()}])
  if mode=='error':raise dbus.exceptions.DBusException('synthetic refusal',name='org.freedesktop.portal.Error.Failed')
  token=str(options['handle_token']);prefix=PATH+'/request/'+sender.lstrip(':').replace('.','_')+'/'
  handle=prefix+('legacy_token' if mode=='legacy' else token)
  if mode=='invalid-handle':return dbus.ObjectPath('/wrong/handle')
  request=Request(bus,handle);requests.append(request)
  if mode in ('early','legacy'):request.Response(dbus.UInt32(0),{})
  elif mode=='owner-loss':GLib.timeout_add(10,lambda:bus.release_name('org.freedesktop.portal.Desktop'))
  elif mode not in ('timeout','client-close'):
   def respond():request.Response(dbus.UInt32({'cancel':1,'failure':2}.get(mode,0)),{});return False
   GLib.timeout_add(30,respond)
  return dbus.ObjectPath(handle)
requests=[];portal=Portal(bus,PATH)
Path(str(output)+'.ready').write_text('ready');GLib.MainLoop().run()
