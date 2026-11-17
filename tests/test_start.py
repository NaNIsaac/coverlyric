import os
import subprocess
import sys

CHILD = """
import os, sys
import coverlyric
assert "numpy" not in sys.modules, "the package imported numpy before setting the thread limits"
print(os.environ["OPENBLAS_NUM_THREADS"], os.environ["OMP_NUM_THREADS"])
import coverlyric.render
"""


def test_package_limits_blas_threads_before_numpy_is_imported():
    env = {
        k: v for k, v in os.environ.items() if k not in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    }
    run = subprocess.run(
        [sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["1", "1"]


def test_a_value_set_by_the_user_is_kept():
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "4"}
    code = "import os, coverlyric; print(os.environ['OPENBLAS_NUM_THREADS'])"
    run = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert run.stdout.strip() == "4"


def test_the_page_starts_in_a_home_folder_that_does_not_exist_yet(tmp_path):
    """Issue #11: the log file in the home folder was opened before the folder was made."""
    home = tmp_path / "new" / "home"
    proc = subprocess.Popen(
        [sys.executable, "-m", "coverlyric", "app", "--home", str(home), "--no-browser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        first = proc.stdout.readline()
        assert "http://127.0.0.1:" in first, first
        assert (home / "coverlyric.log").is_file()
    finally:
        proc.kill()
        proc.wait()
