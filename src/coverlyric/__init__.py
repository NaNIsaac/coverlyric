"""Make a lyric video from a song, a square cover and the lyrics."""

import os

# numpy's OpenBLAS allocates a buffer per CPU core on import, which fails on PCs with many cores
# and little free memory (issue #1). Nothing here does linear algebra, so one thread is enough. This
# runs before any module of the package imports numpy, including in the render workers.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

__version__ = "0.1.0"
