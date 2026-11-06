"""Pruebas del CLI de juguete."""
import io
import contextlib
import demo_cli


def test_saluda():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert demo_cli.main(["saluda"]) == 0
    assert buf.getvalue().strip() == "hola"
