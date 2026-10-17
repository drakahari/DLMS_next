"""Capture bounds must preserve raw bytes without stopping the application."""
from io import BytesIO,StringIO
import json
import pytest
from tests.windows.normal_graphics_capture import BoundedLog,drain_capture


def test_exact_raw_prefix_and_one_footer_when_limit_reached():
    raw,index=BytesIO(),StringIO();capture=BoundedLog(raw,index,limit=7)
    capture.feed(b'abc\r\n');capture.feed(b'XYZ\n');capture.feed(b'discarded')
    capture.stop('application-exit')
    assert raw.getvalue()==b'abc\r\nXY'
    rows=[json.loads(s) for s in index.getvalue().splitlines()]
    assert [(r['offset'],r['bytes']) for r in rows if r['event']=='chunk']==[(0,5),(5,2)]
    assert len([r for r in rows if r['event']=='capture-stop'])==1 and capture.reason=='byte-limit'


def test_duration_and_record_limits_only_stop_recording():
    now=[1.0];raw,index=BytesIO(),StringIO()
    capture=BoundedLog(raw,index,seconds=2,clock=lambda:now[0]);capture.feed(b'first')
    now[0]=3.0;capture.feed(b'late');capture.feed(b'later')
    assert raw.getvalue()==b'first' and capture.reason=='duration'
    raw,index=BytesIO(),StringIO();capture=BoundedLog(raw,index,records=1)
    capture.feed(b'first');capture.feed(b'late')
    assert raw.getvalue()==b'first' and capture.reason=='record-limit'


class Source:
    def __init__(self):self.blocks=[b'first',b'second',b'third',b''];self.reads=0
    def read1(self,size):
        self.reads+=1
        return self.blocks.pop(0)


class FailedWrite:
    def write(self,value):raise OSError('synthetic disk failure')
    def flush(self):raise OSError('synthetic flush failure')


@pytest.mark.parametrize('stage',['raw','index','startup','result','interrupt'])
def test_failures_preserve_pipe_drain_until_owner_exit(stage):
    source=Source();raw=FailedWrite() if stage=='raw' else BytesIO()
    index=FailedWrite() if stage=='index' else StringIO()
    capture=BoundedLog(raw,index);finished=[]
    def started():
        if stage=='startup':raise OSError('synthetic metadata failure')
        if stage=='interrupt':raise KeyboardInterrupt
    def finish():
        finished.append(True)
        if stage=='result':raise OSError('synthetic result failure')
    drain_capture(source,capture,started,finish)
    assert source.reads==4 and not source.blocks and finished==[True]
    assert capture.errors
    if stage=='index':assert capture.bytes==len(raw.getvalue())==5
    if stage in {'startup','interrupt'}:assert raw.getvalue()==b''
    if stage=='result':assert raw.getvalue()==b'firstsecondthird'


def test_short_raw_write_is_counted_and_remaining_pipe_discarded():
    class ShortWrite(BytesIO):
        def write(self,value):return super().write(value[:2])
    raw=ShortWrite();capture=BoundedLog(raw,StringIO());source=Source()
    drain_capture(source,capture)
    assert raw.getvalue()==b'fi' and capture.bytes==2
    assert capture.reason=='collector-error' and source.reads==4


def test_interrupt_during_logging_stops_recording_without_abandoning_pipe():
    class InterruptedWrite:
        def write(self,value):raise KeyboardInterrupt
        def flush(self):pass
    source=Source();capture=BoundedLog(InterruptedWrite(),StringIO())
    drain_capture(source,capture)
    assert source.reads==4 and capture.reason=='collector-error'
