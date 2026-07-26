from pathlib import Path
import unittest
from tests.frontend_source import read_frontend_source


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = read_frontend_source()
SHARED_CARDS_SOURCE = (ROOT / "src" / "components" / "SharedMovieCards.jsx").read_text(encoding="utf-8")
STYLES_SOURCE = (ROOT / "src" / "styles.css").read_text(encoding="utf-8")


class AiControlUiTest(unittest.TestCase):
    def test_sidebar_and_workspace_show_experimental_badge(self):
        self.assertIn("id: 'ai-control'", APP_SOURCE)
        self.assertIn("AI Control", APP_SOURCE)
        self.assertIn("ExperimentalBadge", APP_SOURCE)
        self.assertIn("ai-control-nav-badge", APP_SOURCE)

    def test_prompting_guide_renders_under_command_box(self):
        for text in [
            "Find Tom Cruise movies I own",
            "Create a list of top rated sci-fi from 2010",
            "Download unowned Nolan movies in 1080p",
            "Delete files larger than 10 GB",
            "No action runs automatically. Every result is reviewed before you confirm it.",
        ]:
            self.assertIn(text, APP_SOURCE)

    def test_execute_button_depends_on_reviewed_plan_id(self):
        self.assertIn("executeAiControlPlan", APP_SOURCE)
        self.assertIn("confirmDisabled={!aiControlPlan?.plan_id", APP_SOURCE)
        self.assertIn("/api/ai-control/preview", APP_SOURCE)
        self.assertIn("/api/ai-control/execute", APP_SOURCE)

    def test_ai_control_trusted_indexers_use_dialog_not_inline_long_list(self):
        self.assertIn("aiControlIndexerDialogOpen", APP_SOURCE)
        self.assertIn("AIControlIndexerDialog", APP_SOURCE)
        self.assertIn("AI Control download trust", APP_SOURCE)
        self.assertIn("AI Control trusted indexers", APP_SOURCE)
        self.assertNotIn("ai-control-indexer-list", APP_SOURCE)

    def test_ai_control_defaults_to_yts_copy_is_visible(self):
        self.assertIn("YTS/YIFY default", APP_SOURCE)
        self.assertIn("Default AI Control download source.", APP_SOURCE)

    def test_ai_control_styles_exist(self):
        self.assertIn(".ai-control-workspace", STYLES_SOURCE)
        self.assertIn(".experimental-badge", STYLES_SOURCE)
        self.assertIn(".ai-control-guide", STYLES_SOURCE)

    def test_ai_control_blocked_results_are_reported_without_a_second_results_owner(self):
        self.assertIn("could not be included in the selectable plan", APP_SOURCE)
        self.assertNotIn("function AIControlTable", APP_SOURCE)

    def test_ai_control_preview_loading_shows_staged_messages(self):
        for text in [
            "Understanding request with Ollama...",
            "Contacting TMDB...",
            "Checking your library...",
            "Searching trusted indexers...",
            "Preparing review...",
        ]:
            self.assertIn(text, APP_SOURCE)

    def test_every_valid_ai_control_action_uses_card_results(self):
        for text in [
            "ai-control-card-results",
            "AIControlCardResults",
            "DiscoverMovieCard",
            "const ready = plan.state === 'valid_plan'",
        ]:
            self.assertIn(text, APP_SOURCE)
        self.assertNotIn("Display as cards", APP_SOURCE)
        self.assertNotIn("Back to table", APP_SOURCE)

    def test_ai_control_cards_reuse_discover_cards_and_shared_bulk_list_owner(self):
        result_source = APP_SOURCE[
            APP_SOURCE.index("function AIControlResult"):
            APP_SOURCE.index("function AIControlCardResults")
        ]
        for text in [
            "AIControlCardResults",
            "selectedAiControlKeys",
            "reviewedDownloads",
            "onConfirm={confirmAction}",
            "onFindSources={openSourceReview}",
        ]:
            self.assertIn(text, APP_SOURCE)
        card_source = APP_SOURCE[APP_SOURCE.index("function AIControlCardResults"):]
        for text in [
            "DiscoverMovieCard",
            "Add to list",
            "onAddBulk={addAiControlMoviesToList}",
            "Select all results",
            "Find sources",
            "Confirm action",
        ]:
            self.assertIn(text, card_source)

    def test_ai_control_card_view_can_surface_preserved_cast_and_directors(self):
        discover_card_source = SHARED_CARDS_SOURCE[
            SHARED_CARDS_SOURCE.index("function DiscoverMovieCard"):
            SHARED_CARDS_SOURCE.index("function MovieExpandedDetails")
        ]
        self.assertIn("directors={displayMovie.directors}", discover_card_source)
        self.assertIn("cast={displayMovie.cast}", discover_card_source)

    def test_ai_control_results_render_pagination_and_total_count(self):
        for text in [
            "ai-control-pagination",
            "total_matches",
            "currentPage",
            "Previous page",
            "Next page",
        ]:
            self.assertIn(text, APP_SOURCE)

    def test_ai_control_selection_starts_complete_persists_across_pages_and_executes_server_keys(self):
        for text in [
            "new Set((plan?.items || []).map((item) => item.selection_key).filter(Boolean))",
            "selectedAiControlKeys.has(row.selection_key)",
            "selected_keys: selectedKeys",
            "reviewed_downloads: reviewedDownloads",
            "Exact command selection: all",
            "Customized selection:",
        ]:
            self.assertIn(text, APP_SOURCE)

    def test_ai_control_find_sources_is_review_only_until_confirm(self):
        for text in [
            "previewSourceReview(selectedRows, { policy: 'ai_control' })",
            "onReviewComplete",
            "setReviewedDownloads",
        ]:
            self.assertIn(text, APP_SOURCE)

    def test_ai_control_large_delete_requires_confirmation_phrase(self):
        for text in [
            "selectedCount > 50",
            "expectedDeletePhrase",
            "confirmation_phrase: confirmationPhrase",
            "Type the confirmation phrase",
            "setAiControlDangerPhrase",
        ]:
            self.assertIn(text, APP_SOURCE)

    def test_ai_control_execution_uses_a_receipt_and_invalidates_list_cache(self):
        for text in [
            "aiControlReceipt",
            "ai-control-execution-receipt",
            "movies saved",
            "clearUserListsCache()",
            "announceCurationChanged()",
        ]:
            self.assertIn(text, APP_SOURCE)


if __name__ == "__main__":
    unittest.main()
