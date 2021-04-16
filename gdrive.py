from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive


class GDrive:
    def __init__(self):
        self.auth, self.drive = None, None
        self._credentials_file_name = 'credentials.txt'

    def login(self):
        self.auth = GoogleAuth()
        self.auth.LoadCredentialsFile(self._credentials_file_name)
        if self.auth.credentials is None:
            self.auth.LocalWebserverAuth()
        elif self.auth.access_token_expired:
            self.auth.Refresh()
        else:
            self.auth.Authorize()
        self.auth.SaveCredentialsFile(self._credentials_file_name)
        self.auth.LocalWebserverAuth()
        self.drive = GoogleDrive(self.auth)

    def get_folder(self, folder_name):
        folders = self.drive.ListFile({
            'q': f"title='{folder_name}' and mimeType contains 'application/vnd.google-apps.folder' and trashed=false"
        }).GetList()
        return folders[0]

    def create_new_folder(self, new_folder_name, parent_folder=None):
        new_folder = self.drive.CreateFile(
            {'title': f'{new_folder_name}',
             'mimeType': 'application/vnd.google-apps.folder'})
        if parent_folder is not None:
            new_folder['parents'] = [{u'id': parent_folder['id']}]
        new_folder.Upload()
        return new_folder

    def upload_new_file(self, file, folder):
        new_file = self.drive.CreateFile({
            'title': file,
            'parents': [{u'id': folder['id']}]
        })
        new_file.SetContentFile(file)
        new_file.Upload()
        return new_file
