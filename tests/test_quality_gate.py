
from pipeline_coach.coach.quality_gate import validate_action

# --- valid actions ---


def test_valid_action_passes():
    assert (
        validate_action(
            "Schedule a call with the VP of Sales.", issues_text="- Close date has passed"
        )
        is True
    )


def test_valid_action_with_verb_at_start():
    assert (
        validate_action("Send the updated proposal by Thursday.", issues_text="- Missing amount")
        is True
    )


# --- empty / whitespace / None ---


def test_none_fails():
    assert validate_action(None, issues_text="- some issue") is False


def test_empty_string_fails():
    assert validate_action("", issues_text="- some issue") is False


def test_whitespace_only_fails():
    assert validate_action("   ", issues_text="- some issue") is False


# --- restatements ---


def test_exact_restatement_fails():
    issues_text = "- Close date has passed"
    assert validate_action("Close date has passed", issues_text=issues_text) is False


def test_exact_restatement_with_prefix_stripped():
    issues_text = "- The deal is missing an amount"
    assert validate_action("The deal is missing an amount", issues_text=issues_text) is False


def test_similar_restatement_high_overlap_fails():
    # 5 of 6 words overlap (>80%) → restatement
    issues_text = "- Deal has no close date set"
    assert validate_action("Deal has no close date set at all", issues_text=issues_text) is False


def test_low_overlap_not_restatement():
    issues_text = "- No activity logged in 30 days"
    assert (
        validate_action(
            "Schedule a demo call with the prospect this week", issues_text=issues_text
        )
        is True
    )


# --- action verb presence ---


def test_noun_phrase_only_fails():
    assert validate_action("The deal amount.", issues_text="- Missing amount") is False


def test_verb_in_second_word_passes():
    assert (
        validate_action("Please review the contract terms.", issues_text="- Stage stale") is True
    )


def test_verb_in_third_word_passes():
    assert (
        validate_action("AE should contact the decision maker.", issues_text="- Missing DM")
        is True
    )


def test_verb_beyond_third_word_fails():
    # "Outstanding invoice payment review" — "review" is 4th word, no verb in first 3
    assert (
        validate_action(
            "Outstanding invoice payment review needed.", issues_text="- Missing amount"
        )
        is False
    )
