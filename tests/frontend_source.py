from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FRONTEND_OWNER_FILES = (
    "src/App.jsx",
    "src/features/home/HomeWorkspace.jsx",
    "src/features/library/LibraryWorkspace.jsx",
    "src/components/Pagination.jsx",
    "src/features/movie-lists/MovieListsWorkspace.jsx",
    "src/features/cleanup/CleanupWorkspace.jsx",
    "src/features/discover/DiscoverWorkspace.jsx",
    "src/components/Rating.jsx",
    "src/features/ai-control/AIControlWorkspace.jsx",
    "src/features/downloads/DownloadsWorkspace.jsx",
    "src/features/help/HelpWorkspace.jsx",
    "src/features/settings/SettingsWorkspace.jsx",
    "src/components/SharedMovieCards.jsx",
    "src/components/DiscoverResultGrid.jsx",
    "src/components/TorrentActions.jsx",
    "src/components/LibraryControls.jsx",
    "src/components/ListEditorModal.jsx",
    "src/components/ExportCopyDialog.jsx",
    "src/components/MetadataCorrectionModal.jsx",
    "src/components/MetadataAuthorityPanel.jsx",
    "src/components/IdentityReviewPanel.jsx",
    "src/components/PosterEditorModal.jsx",
    "src/components/SmartMatchPanel.jsx",
    "src/api/client.js",
    "src/api/curation.js",
    "src/api/library.js",
    "src/api/metadata.js",
    "src/api/qbittorrent.js",
    "src/discoverUtils.js",
    "src/utils/appUtils.js",
    "src/utils/cleanupUtils.js",
    "src/utils/libraryUtils.js",
    "src/utils/moviePresentation.js",
)


def read_frontend_source():
    return "\n".join(
        (ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in FRONTEND_OWNER_FILES
    )
