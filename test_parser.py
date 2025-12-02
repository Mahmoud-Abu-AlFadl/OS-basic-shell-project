from parser import parse_line

def test_simple():
    res = parse_line("ls -l /tmp")
    assert res[0]["argv"] == ["ls","-l","/tmp"]
