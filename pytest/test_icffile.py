import pytest
from icf import pyicf
from icf import ICFFile
import os

@pytest.fixture(params=[ICFFile, pyicf.ICFFile])
def icf_impl(request):
    return request.param


def test_write_and_readback_from_icffile(icf_impl):
    os.remove("/tmp/test.icf")
    f = icf_impl("/tmp/test.icf")
    testdata1 = b'blablakaskdlaskd'
    testdata2 = b'blabasdasdlakaskdlaskd'
    f.write(testdata1)
    f.write(testdata2)
    original_timestamp = f.get_timestamp()
    assert f.size() == 2, "Correct number of entries"
    f.close()
    # open file again
    f = icf_impl("/tmp/test.icf")
    assert f.get_timestamp() == original_timestamp, "Read back correct timestamp"
    assert f.size() == 2, "Read back correct number of entries"
    assert f.read_at(0) == testdata1, "Read back correct data"
    assert f.read_at(1) == testdata2, "Read back correct data"

def test_read_while_writing(icf_impl):
    os.remove("/tmp/test.icf")
    f = icf_impl("/tmp/test.icf")
    testdata1 = b'blablakaskdlaskd'
    testdata2 = b'blabasdasdlakaskdlaskd'
    f.write(testdata1)
    f.write(testdata2)
    assert f.read_at(0) == testdata1, "Read back correct data"
    assert f.read_at(1) == testdata2, "Read back correct data"


def test_write_read_multiple_bunches(icf_impl):
    os.remove("/tmp/test.icf")
    f = pyicf.ICFFile("/tmp/test.icf",bunchsize=50)
    data = b"0"*26

    for i in range(6):
        f.write(data)
    assert f._bunch_number == 3, "Correct number of bunches"
    f.close()

    f = pyicf.ICFFile("/tmp/test.icf")

    for i in range(6):
        assert f.read_at(i) == data



def test_bunch_buffer():
    n = 10
    bf = pyicf.icffile.BunchBuffer(n)

    for i in range(n):
        bf[i] = [i]
    for i in range(n):
        assert i in bf, "Element still in Bunch Buffer"

    bf[n] = [n]
    assert n in bf, "New element in Bunch Buffer"
    assert 0 not in bf, "Oldest element removed from Bunch Buffer"
