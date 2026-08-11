"""The builders' one guarantee, checked rather than documented.

Every builder that accepts ``tags=`` has to put them where decide() reads
them. A builder that left them at the cell's top level instead would hand a
test a cell that looks tagged and is not, and the test would go on asserting
about a tag nothing acts on.
"""

import pytest

from ipynb_scrubber.actions import Omit, Scrubber, ScrubbingOptions
from tests.builders import code, markdown, raw, schema_valid_code

OPTS = ScrubbingOptions()
SCRUBBER = Scrubber.for_options(OPTS)

TAG_BUILDERS = [code, markdown, raw, schema_valid_code]
TAG_BUILDER_IDS = [builder.__name__ for builder in TAG_BUILDERS]


@pytest.mark.parametrize('builder', TAG_BUILDERS, ids=TAG_BUILDER_IDS)
def test_tags_land_where_decide_reads_them(builder):
    """metadata.tags, not the cell's top level, which nothing ever reads."""
    built = builder('x = 1', tags=[OPTS.omit_tag])

    assert built['metadata']['tags'] == [OPTS.omit_tag]
    assert 'tags' not in built
    assert SCRUBBER.decide(built) == Omit()
