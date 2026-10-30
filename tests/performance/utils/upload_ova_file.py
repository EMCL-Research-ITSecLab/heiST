import os
import math
from dotenv import load_dotenv, find_dotenv
import time

from tools.challenges.yaml_parser import retrieve_ova_data

YAML_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../tools/challenges"))

env_file = find_dotenv()
load_dotenv(env_file)

SERVER_HOST = os.getenv("SERVER_HOST", "localhost")
SERVER_PORT = os.getenv("SERVER_PORT", "8000")
SERVER_PROTOCOL = os.getenv("SERVER_PROTOCOL", "https")

API_URL = f"{SERVER_PROTOCOL}://{SERVER_HOST}:{SERVER_PORT}/backend/upload-diskfile.php"
CONFIG_URL = f"{SERVER_PROTOCOL}://{SERVER_HOST}:{SERVER_PORT}/config/general.config.json"


def load_config(session):
    response = session.get(CONFIG_URL)
    if response.status_code != 200:
        raise Exception(f"Failed to load config: {response.text}")
    return response.json()["upload"]


def init_upload(file_path, session, chunk_size, target_filename=None, prints=False):
    if prints:
        print("\tInitializing upload")
    file_name = os.path.basename(file_path) if not target_filename else target_filename

    if len(file_name.split(".")) < 2 or not file_name.split(".")[-1].lower() in ["ova", "ovf"]:
        file_name += ".ova"

    file_size = os.path.getsize(file_path)
    total_chunks = math.ceil(file_size / chunk_size)
    init_payload = {
        "phase": "init",
        "fileName": file_name,
        "fileSize": file_size,
        "uploadId": f"{int(time.time())}-{file_name}",
        "totalChunks": total_chunks
    }
    response = session.post(API_URL, json=init_payload)
    if response.status_code != 200 or not response.json().get("success"):
        raise Exception(f"Failed to initialize upload: {response.text}")

    uploadId = response.json().get("uploadId")
    expected_chunk_size = response.json().get("chunkSize")
    if expected_chunk_size != chunk_size:
        if prints:
            print(f"\tWarning: Server expects chunk size {expected_chunk_size}, but client is using {chunk_size}. Adjusting chunk size.")
        chunk_size = expected_chunk_size
        total_chunks = math.ceil(file_size / chunk_size)
        if prints:
            print(f"\tNew total chunks: {total_chunks}")

    return uploadId, total_chunks


def upload_chunk_by_chunk(file_path, session, uploadId, chunk_size, total_chunks, prints=False):
    for chunk_index in range(total_chunks):
        if prints:
            print(f"\tUploading chunk {chunk_index + 1}/{total_chunks}")
        with open(file_path, "rb") as f:
            f.seek(chunk_index * chunk_size)
            chunk_data = f.read(chunk_size)

        files = {
            "chunk": ("chunk.bin", chunk_data)
        }
        data = {
            "uploadId": uploadId,
            "chunkIndex": chunk_index
        }

        response = session.post(API_URL, data=data, files=files)
        if response.status_code != 200 or not response.json().get("success"):
            raise Exception(f"Failed to upload chunk {chunk_index}: {response.text}")


def finalize_upload(uploadId, session, prints=False):
    if prints:
        print("\tFinalizing upload")
    finalize_payload = {
        "phase": "finalize",
        "uploadId": uploadId
    }
    response = session.post(API_URL, json=finalize_payload)
    if response.status_code != 200 or not response.json().get("success"):
        raise Exception(f"Failed to finalize upload: {response.text}")


def upload_ova_file(file_path, session, target_filename=None, prints=False):
    config = load_config(session)
    chunk_size = config.get("CHUNK_SIZE", 1048576)

    uploadId, total_chunks = init_upload(file_path, session, chunk_size, target_filename, prints=prints)
    upload_chunk_by_chunk(file_path, session, uploadId, chunk_size, total_chunks, prints=prints)
    finalize_upload(uploadId, session, prints=prints)


def upload_all_ova_files(admin_session, path_to_yaml, prints=False):
    ova_files = retrieve_ova_data(path_to_yaml)
    for ova in ova_files:
        if prints:
            print(f"Uploading OVA: {ova['name']} from {ova['path']}")
        upload_ova_file(ova['path'], admin_session, target_filename=ova['name'], prints=prints)


if __name__ == "__main__":
    from tests.performance.utils.get_authenticated_session import get_authenticated_session

    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    session = get_authenticated_session(ADMIN_USER, ADMIN_PASSWORD)

    CONFIG_PATH = os.path.join(YAML_DIR, "ctf-config.yaml")
    upload_all_ova_files(session, CONFIG_PATH, prints=True)

