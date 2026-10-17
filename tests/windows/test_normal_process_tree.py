"""No process launch/termination: reject stale parent PID lineage in harnesses."""
import os
import pytest

@pytest.mark.skipif(os.name!='nt',reason='Windows external harness import')
def test_recycled_parent_does_not_adopt_older_browser():
    from tests.windows.normal_processes import birth_safe_descendants
    rows={10:0,11:10,12:10,13:12,14:11,15:11,16:10}
    starts={10:100,11:110,12:90,13:130,14:115,15:105}
    assert birth_safe_descendants(10,rows,starts.get,200)=={10,11,14}
    assert birth_safe_descendants(999,rows,starts.get,200)==set()
    calls=[]
    def changed(pid):
        calls.append(pid)
        return (101 if calls.count(10)>1 else 100) if pid==10 else starts.get(pid)
    assert birth_safe_descendants(10,rows,changed,200)==set()

@pytest.mark.skipif(os.name!='nt',reason='Windows external harness import')
def test_snapshot_cutoff_and_changed_intermediate_prune_branch():
    from tests.windows.normal_processes import birth_safe_descendants
    rows={10:0,11:10,12:11,13:10}
    starts={10:100,11:110,12:120,13:250}
    assert birth_safe_descendants(10,rows,starts.get,200)=={10,11,12}
    calls={}
    def changed(pid):
        calls[pid]=calls.get(pid,0)+1
        return 111 if pid==11 and calls[pid]>1 else starts.get(pid)
    assert birth_safe_descendants(10,rows,changed,200)=={10}
    assert birth_safe_descendants(10,rows,starts.get,99)==set()
