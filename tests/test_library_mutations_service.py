import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from services.library_mutations import LibraryMutationError, LibraryMutationService


class LibraryMutationServiceTest(unittest.TestCase):
    def test_cleanup_trashes_complete_dedicated_movie_folder_with_sidecars(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'Alien (1979)'
            folder.mkdir()
            movie = folder / 'Alien.1979.mkv'
            movie.write_bytes(b'movie')
            (folder / 'Alien.1979.srt').write_text('subtitles', encoding='utf-8')
            (folder / 'poster.jpg').write_bytes(b'poster')
            metadata_store = Mock()
            trash_file = Mock()
            service = LibraryMutationService([root], metadata_store, {'.mkv'}, trash_file=trash_file)

            preview = service.plan_deletions([movie], whole_movie_folders=True)
            result = service.delete_many([movie], use_trash=True, whole_movie_folders=True)

        self.assertEqual(preview['folder_count'], 1)
        self.assertEqual(preview['actions'][0]['target'], str(folder.resolve()))
        self.assertEqual(preview['actions'][0]['sidecar_count'], 2)
        trash_file.assert_called_once_with(str(folder.resolve()))
        metadata_store.remove_path_records.assert_called_once_with(str(movie.resolve()))
        self.assertEqual(result['deleted_paths'], [str(movie.resolve())])
        self.assertEqual(result['folder_count'], 1)

    def test_cleanup_never_expands_file_deletion_without_confirmed_folder_target(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'Alien (1979)'
            folder.mkdir()
            movie = folder / 'Alien.1979.mkv'
            movie.write_bytes(b'movie')
            (folder / 'poster.jpg').write_bytes(b'poster')
            trash_file = Mock()
            service = LibraryMutationService([root], Mock(), {'.mkv'}, trash_file=trash_file)

            result = service.delete_many(
                [movie],
                use_trash=True,
                whole_movie_folders=True,
                allowed_folder_targets=[],
            )

        self.assertEqual(result['folder_count'], 0)
        trash_file.assert_called_once_with(str(movie.resolve()))

    def test_cleanup_keeps_folder_when_another_video_is_not_selected(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'Alien Collection'
            folder.mkdir()
            selected = folder / 'Alien.1979.mkv'
            selected.write_bytes(b'movie')
            (folder / 'Aliens.1986.mkv').write_bytes(b'movie')
            trash_file = Mock()
            service = LibraryMutationService([root], Mock(), {'.mkv'}, trash_file=trash_file)

            preview = service.plan_deletions([selected], whole_movie_folders=True)
            service.delete_many([selected], use_trash=True, whole_movie_folders=True)

        self.assertEqual(preview['folder_count'], 0)
        self.assertEqual(preview['actions'][0]['target'], str(selected.resolve()))
        trash_file.assert_called_once_with(str(selected.resolve()))

    def test_cleanup_trashes_folder_when_every_video_in_it_is_selected(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'Alien Two Disc'
            folder.mkdir()
            first = folder / 'Alien.CD1.mkv'
            second = folder / 'Alien.CD2.mkv'
            first.write_bytes(b'one')
            second.write_bytes(b'two')
            (folder / 'poster.jpg').write_bytes(b'poster')
            trash_file = Mock()
            metadata_store = Mock()
            service = LibraryMutationService([root], metadata_store, {'.mkv'}, trash_file=trash_file)

            result = service.delete_many(
                [first, second],
                use_trash=True,
                whole_movie_folders=True,
            )

        trash_file.assert_called_once_with(str(folder.resolve()))
        self.assertCountEqual(result['deleted_paths'], [str(first.resolve()), str(second.resolve())])
        self.assertEqual(metadata_store.remove_path_records.call_count, 2)

    def test_cleanup_keeps_folder_when_it_contains_unrecognized_data(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'Alien (1979)'
            folder.mkdir()
            movie = folder / 'Alien.1979.mkv'
            movie.write_bytes(b'movie')
            (folder / 'valuable-backup.bin').write_bytes(b'not a sidecar')
            trash_file = Mock()
            service = LibraryMutationService([root], Mock(), {'.mkv'}, trash_file=trash_file)

            preview = service.plan_deletions([movie], whole_movie_folders=True)
            service.delete_many([movie], use_trash=True, whole_movie_folders=True)

        self.assertEqual(preview['folder_count'], 0)
        trash_file.assert_called_once_with(str(movie.resolve()))

    def test_cleanup_treats_unsupported_video_as_unrecognized_data(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'Mixed Formats'
            folder.mkdir()
            movie = folder / 'recognized.mkv'
            movie.write_bytes(b'movie')
            (folder / 'rare-copy.divx').write_bytes(b'other movie')
            trash_file = Mock()
            service = LibraryMutationService([root], Mock(), {'.mkv'}, trash_file=trash_file)

            preview = service.plan_deletions([movie], whole_movie_folders=True)
            service.delete_many([movie], use_trash=True, whole_movie_folders=True)

        self.assertEqual(preview['folder_count'], 0)
        trash_file.assert_called_once_with(str(movie.resolve()))

    def test_delete_updates_catalog_after_filesystem_success(self):
        with tempfile.TemporaryDirectory() as root:
            movie = Path(root) / 'Alien.1979.mkv'
            movie.write_bytes(b'movie')
            metadata_store = Mock()
            service = LibraryMutationService([root], metadata_store, {'.mkv'})

            result = service.delete(movie, use_trash=False)

        self.assertFalse(movie.exists())
        self.assertEqual(result['deleted'], str(movie.resolve()))
        metadata_store.remove_path_records.assert_called_once_with(str(movie.resolve()))

    def test_delete_does_not_update_catalog_when_trash_fails(self):
        with tempfile.TemporaryDirectory() as root:
            movie = Path(root) / 'Alien.1979.mkv'
            movie.write_bytes(b'movie')
            metadata_store = Mock()
            service = LibraryMutationService(
                [root], metadata_store, {'.mkv'},
                trash_file=Mock(side_effect=OSError('trash unavailable')),
            )

            with self.assertRaises(OSError):
                service.delete(movie, use_trash=True)

        metadata_store.remove_path_records.assert_not_called()

    def test_delete_rejects_files_outside_library_roots(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            movie = Path(outside) / 'Alien.1979.mkv'
            movie.write_bytes(b'movie')
            service = LibraryMutationService([root], Mock(), {'.mkv'})

            with self.assertRaises(LibraryMutationError):
                service.delete(movie, use_trash=False)


if __name__ == '__main__':
    unittest.main()
