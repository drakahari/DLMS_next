"""The public normal-package observer must not inspect a reused test PID."""
import ctypes
import os
from types import SimpleNamespace

import pytest

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows owned-process inspection helper')


def test_module_observer_rechecks_birth_before_any_module_read(monkeypatch):
    from tests.windows import normal_processes as module
    real=module.c
    class Proxy:
        def __getattr__(self,name):return getattr(real,name)
        def WinDLL(self,*args,**kwargs):return object()
    monkeypatch.setattr(module,'c',Proxy())
    monkeypatch.setattr(module,'descendants',lambda parent:{42})
    identities=iter([{'start':1,'image':'owned.exe'},{'start':2,'image':'other.exe'}])
    monkeypatch.setattr(module,'identity',lambda pid:next(identities))
    monkeypatch.setattr(module,'open_process',lambda *args:123)
    closed=[];monkeypatch.setattr(module,'close',closed.append)
    reads=[]
    monkeypatch.setattr(module,'api',lambda *args:lambda *values:reads.append(True))
    assert module.modules(1)==[{'pid':42,'inspection_error':'ValueError'}]
    assert reads==[] and closed==[123]
