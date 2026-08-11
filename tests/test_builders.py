"""The builders' own guarantees, checked rather than documented.

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


@pytest.mark.parametrize('builder', TAG_BUILDERS, ids=TAG_BUILDER_IDS)
def test_tags_compose_with_the_rest_of_a_cells_metadata(builder):
    """Neither argument clobbers the other, so both can be said at once."""
    built = builder('x = 1', tags=[OPTS.omit_tag], metadata={'jupyter': {'source': 1}})

    assert built['metadata'] == {'jupyter': {'source': 1}, 'tags': [OPTS.omit_tag]}


@pytest.mark.parametrize('builder', TAG_BUILDERS, ids=TAG_BUILDER_IDS)
def test_saying_tags_twice_is_refused(builder):
    """The one composition with no sensible answer is an error, not a winner."""
    with pytest.raises(TypeError, match='tags given twice'):
        builder('x = 1', tags=['a'], metadata={'tags': ['b']})


@pytest.mark.parametrize('builder', [code, markdown, raw], ids=['code', 'md', 'raw'])
def test_an_untagged_cell_carries_no_metadata(builder):
    """Cells arrive without the key, and tests of that path need one that does."""
    assert 'metadata' not in builder('x = 1')
