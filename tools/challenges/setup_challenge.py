import os
import time
import datetime
from tools.challenges.upload_ova_file import upload_all_ova_files
from .client import request

YAML_DIR = os.path.abspath(os.path.dirname(__file__))




def setup_challenge(admin_session, path_to_yaml, upload_ovas=True, prints=False):
    start_time = time.time()

    if prints:
        print("Setting up challenge from:", path_to_yaml)

    if upload_ovas:
        if prints:
            print("\nUploading all OVA files for the challenge")
        upload_all_ova_files(admin_session, path_to_yaml, prints=prints)

    if prints:
        print("\nPreparing form data from YAML")
    with open(path_to_yaml, encoding='utf-8') as source:
        yaml_source = source.read(256*1024+1)
    if len(yaml_source.encode('utf-8')) > 256*1024:
        raise ValueError('YAML file must be at most 256 KiB')
    # Use the browser's parser and owned-image lookup. Upload filenames and
    # registered display names deliberately have different suffix conventions.
    form_data = request(admin_session, 'POST', '/api/admin/challenges/import-yaml',
                        json={'yaml': yaml_source})['data']

    if prints:
        print("\nCreating challenge on the server")
    result = request(admin_session, 'POST', '/api/admin/challenges', json=form_data, timeout=(10, 1900))
    challenge_id = result.get('id')
    if type(challenge_id) is not int or challenge_id <= 0:
        raise RuntimeError('Exercise creation was not confirmed; inspect existing definitions before retrying')

    end_time = time.time()

    if prints:
        print(f"\nChallenge ID {challenge_id} created successfully")
        print(f"Total time taken: {datetime.timedelta(seconds=end_time - start_time)}")

    return challenge_id


if __name__ == "__main__":
    from tools.challenges.get_authenticated_session import get_authenticated_session

    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    session = get_authenticated_session(ADMIN_USER, ADMIN_PASSWORD)

    CONFIG_PATH = os.path.join(YAML_DIR, "ctf-config.yaml")
    setup_challenge(session, CONFIG_PATH, upload_ovas=True, prints=True)
