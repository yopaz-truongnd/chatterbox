"""Keep direct unittest runs fast and offline by default."""

import os


os.environ.setdefault("CHATTERBOX_TEST_DUMMY_INFERENCE", "1")
