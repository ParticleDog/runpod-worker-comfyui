import time
import requests
import json
import base64
import runpod
from runpod.serverless.utils.rp_validator import validate
from runpod.serverless.modules.rp_logger import RunPodLogger
from requests.adapters import HTTPAdapter, Retry
from schemas.input import INPUT_SCHEMA


BASE_URI = 'http://127.0.0.1:3000'
TIMEOUT = 600

session = requests.Session()
retries = Retry(total=10, backoff_factor=0.1, status_forcelist=[502, 503, 504])
session.mount('http://', HTTPAdapter(max_retries=retries))
logger = RunPodLogger()


# ---------------------------------------------------------------------------- #
#                               ComfyUI Functions                              #
# ---------------------------------------------------------------------------- #

def wait_for_service(url):
    retries = 0

    while True:
        try:
            requests.get(url)
            return
        except requests.exceptions.RequestException:
            retries += 1

            # Only log every 15 retries so the logs don't get spammed
            if retries % 15 == 0:
                logger.info('Service not ready yet. Retrying...')
        except Exception as err:
            logger.error(f'Error: {err}')

        time.sleep(0.2)


def send_get_request(endpoint):
    return session.get(
        url=f'{BASE_URI}/{endpoint}',
        timeout=TIMEOUT
    )


def send_post_request(endpoint, payload):
    return session.post(
        url=f'{BASE_URI}/{endpoint}',
        json=payload,
        timeout=TIMEOUT
    )


# ---------------------------------------------------------------------------- #
#                                RunPod Handler                                #
# ---------------------------------------------------------------------------- #
def handler(event):
    try:
        validated_input = validate(event['input'], INPUT_SCHEMA)

        if 'errors' in validated_input:
            return {
                'error': validated_input['errors']
            }

        payload = validated_input['validated_input']
        logger.debug('Queuing prompt')

        queue_response = send_post_request(
            f'{BASE_URI}/prompt',
            {
                'prompt': payload['prompt']
            }
        )

        resp_json = queue_response.json()

        if queue_response.status_code == 200:
            prompt_id = resp_json['prompt_id']
            logger.info(f'Prompt queued successfully: {prompt_id}')

            while True:
                logger.info(f'Getting status of prompt: {prompt_id}')
                r = send_get_request(f"{BASE_URI}/history/{prompt_id}")
                resp_json = r.json()

                if r.status_code == 200 and len(resp_json):
                    break

                time.sleep(0.2)

            image_filenames = resp_json[prompt_id]['outputs']['9']['images']
            images = []

            for image_filename in image_filenames:
                filename = image_filename['filename']
                image_path = f'/runpod-volume/ComfyUI/output/{filename}'

                with open(image_path, 'rb') as image_file:
                    images.append(base64.b64encode(image_file.read()).decode('utf-8'))

            return {
                'status': 'ok',
                'images': images
            }
        else:
            logger.error(f'HTTP Status code: {queue_response.status_code}')
            logger.error(json.dumps(resp_json, indent=4, default=str))
    except Exception as e:
        logger.error(str(e))
        return {
            'status': 'error',
            'message': str(e)
        }


if __name__ == "__main__":
    wait_for_service(url=f'{BASE_URI}/system_stats')
    logger.info('ComfyUI API is ready')
    logger.info('Starting RunPod Serverless...')
    runpod.serverless.start(
        {
            'handler': handler
        }
    )