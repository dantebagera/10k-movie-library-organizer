import os
import shutil
import stat
from pathlib import Path

from send2trash import send2trash


class LibraryMutationError(RuntimeError):
    pass


class LibraryMutationService:
    """Own filesystem mutations and their matching catalog updates."""

    SIDECAR_EXTENSIONS = {
        '.ass', '.bmp', '.dfxp', '.gif', '.idx', '.jpeg', '.jpg',
        '.log', '.md5', '.nfo', '.png', '.sami', '.sha1', '.sha256',
        '.smi', '.srt', '.ssa', '.sub', '.sup', '.sfv', '.tbn', '.ttml', '.txt',
        '.url', '.usf', '.vtt', '.webp', '.xml',
    }
    SIDECAR_FILENAMES = {'desktop.ini', 'thumbs.db'}

    def __init__(self, roots, metadata_store, video_extensions, trash_file=send2trash):
        self.roots = [Path(root).resolve() for root in roots if root]
        self.metadata_store = metadata_store
        self.video_extensions = {str(ext).lower() for ext in video_extensions}
        self.trash_file = trash_file

    def _library_root(self, path):
        candidate = Path(path).resolve()
        for root in self.roots:
            try:
                candidate.relative_to(root)
                return root
            except ValueError:
                continue
        return None

    def _candidate(self, path):
        candidate = Path(path).resolve()
        root = self._library_root(candidate)
        if root is None:
            raise LibraryMutationError('Path is outside the allowed movies directory')
        if not candidate.is_file():
            raise FileNotFoundError(str(candidate))
        return candidate, root

    def _movie_folder_action(self, folder, root, selected_paths):
        """Return a safe whole-folder action or None when the folder needs file-only deletion."""
        if folder == root or folder.parent != root or not folder.is_dir():
            return None

        video_paths = []
        sidecar_count = 0
        for entry in folder.rglob('*'):
            if entry.is_symlink():
                return None
            if not entry.is_file():
                continue
            resolved = entry.resolve()
            suffix = entry.suffix.lower()
            if suffix in self.video_extensions:
                video_paths.append(resolved)
            elif suffix in self.SIDECAR_EXTENSIONS or entry.name.lower() in self.SIDECAR_FILENAMES:
                sidecar_count += 1
            else:
                # Unknown files may be another media format, an archive, or personal data.
                return None

        if not video_paths or any(path not in selected_paths for path in video_paths):
            return None

        return {
            'target_type': 'folder',
            'target': str(folder),
            'folder': str(folder),
            'paths': [str(path) for path in video_paths],
            'sidecar_count': sidecar_count,
        }

    def plan_deletions(self, paths, *, whole_movie_folders=False, allowed_folder_targets=None):
        """Build a bounded deletion plan without changing the filesystem."""
        candidates = []
        roots = {}
        seen = set()
        for path in paths or []:
            candidate, root = self._candidate(path)
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
            roots[candidate] = root
        if not candidates:
            raise LibraryMutationError('No paths provided')

        selected_paths = set(candidates)
        allowed_folders = None
        if allowed_folder_targets is not None:
            allowed_folders = {Path(path).resolve() for path in allowed_folder_targets}
        actions = []
        covered = set()
        if whole_movie_folders:
            folders = []
            for candidate in candidates:
                root = roots[candidate]
                try:
                    relative = candidate.relative_to(root)
                except ValueError:
                    continue
                if len(relative.parts) < 2:
                    continue
                folder = root / relative.parts[0]
                if allowed_folders is not None and folder.resolve() not in allowed_folders:
                    continue
                if folder not in folders:
                    folders.append(folder)
            for folder in folders:
                root = self._library_root(folder)
                action = self._movie_folder_action(folder, root, selected_paths) if root else None
                if not action:
                    continue
                action_paths = {Path(path).resolve() for path in action['paths']}
                covered.update(action_paths)
                actions.append(action)

        for candidate in candidates:
            if candidate in covered:
                continue
            actions.append({
                'target_type': 'file',
                'target': str(candidate),
                'folder': str(candidate.parent),
                'paths': [str(candidate)],
                'sidecar_count': 0,
            })

        return {
            'paths': [str(candidate) for candidate in candidates],
            'actions': actions,
            'folder_count': sum(action['target_type'] == 'folder' for action in actions),
            'file_count': sum(action['target_type'] == 'file' for action in actions),
        }

    def _execute_action(self, action, *, use_trash):
        target = Path(action['target'])
        if use_trash:
            self.trash_file(str(target))
        elif action['target_type'] == 'folder':
            shutil.rmtree(target)
        else:
            target.unlink()

        for path in action['paths']:
            self.metadata_store.remove_path_records(path)
        return {
            **action,
            'trashed': bool(use_trash),
            'folder_removed': action['target_type'] == 'folder',
        }

    def delete_many(
        self,
        paths,
        *,
        use_trash=True,
        whole_movie_folders=False,
        allowed_folder_targets=None,
    ):
        plan = self.plan_deletions(
            paths,
            whole_movie_folders=whole_movie_folders,
            allowed_folder_targets=allowed_folder_targets,
        )
        completed = []
        failures = []
        for action in plan['actions']:
            try:
                completed.append(self._execute_action(action, use_trash=use_trash))
            except OSError as error:
                failures.append({'target': action['target'], 'error': str(error)})
        deleted_paths = [path for action in completed for path in action['paths']]
        return {
            'success': not failures,
            'deleted_paths': deleted_paths,
            'actions': completed,
            'failures': failures,
            'folder_count': sum(action['target_type'] == 'folder' for action in completed),
            'file_count': sum(action['target_type'] == 'file' for action in completed),
            'trashed': bool(use_trash),
        }

    def delete(self, path, *, use_trash=True):
        candidate, root = self._candidate(path)

        current_mode = candidate.stat().st_mode
        if not (current_mode & stat.S_IWRITE):
            candidate.chmod(current_mode | stat.S_IWRITE)

        action = self.plan_deletions(
            [candidate],
            whole_movie_folders=not use_trash,
        )['actions'][0]
        result = self._execute_action(action, use_trash=use_trash)
        return {
            'success': True,
            'deleted': str(candidate),
            'folder_removed': result['folder_removed'],
            'folder': str(candidate.parent),
            'trashed': bool(use_trash),
            'target': result['target'],
            'target_type': result['target_type'],
        }
