"""Pytest config for the F-net adapter dir.

``conv_test.py`` / ``batch_test.py`` / ``split_test.py`` are ad-hoc manual
probes (run directly as ``python worker/fnet/<name>.py``): they load NIED
credentials and hit the live HinetPy network *at import time*, so pytest's
default ``*_test.py`` collection would import — and fail/hang — them with no
network or credentials.  They are NOT unit tests; the real offline suites are
``test_fetch_fnet_offline.py`` and ``test_fetch_window_offline.py`` (``test_*``).
Exclude the probes from collection so the offline gate is deterministic.
"""

collect_ignore = ["conv_test.py", "batch_test.py", "split_test.py"]
