import asyncio
import base64
import binascii
import threading

from Auth.firebase_messaging import (
    FcmRegisterConfig,
    FcmPushClient,
    FcmPushClientConfig,
    FcmPushClientRunState,
)
from Auth.token_cache import set_cached_value, get_cached_value

class FcmReceiver:

    _instance = None
    _listening = False
    _loop = None
    _loop_thread = None
    # Guards the one-time start of the shared FCM listener against concurrent
    # registrations (the polling loop fetches device locations in parallel).
    _start_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(FcmReceiver, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        # Define Firebase project configuration
        project_id = "google.com:api-project-289722593072"
        app_id = "1:289722593072:android:3cfcf5bc359f0308"
        api_key = "AIzaSyD_gko3P392v6how2H7UpdeXQ0v2HLettc"
        message_sender_id = "289722593072"

        # APK signing certificate SHA1
        android_cert_sha1 = "38918a453d07199354f8b19af05ec6562ced5788"
        bundle_id = "com.google.android.apps.adm"

        self._fcm_config = FcmRegisterConfig(
            project_id=project_id,
            app_id=app_id,
            api_key=api_key,
            messaging_sender_id=message_sender_id,
            bundle_id=bundle_id,
            android_package=bundle_id,
            android_cert_sha1=android_cert_sha1
        )

        # Keep the push client reconnecting through transient FCM/MCS outages
        # instead of self-terminating. With the library default
        # (abort_on_sequential_error_count=3) three sequential read/connection
        # errors permanently shut the listener down; FcmReceiver then never knew
        # to restart it, so every location request timed out forever and all
        # trackers went stale. None = keep resetting; the higher retry count
        # rides out longer blips before _reset gives up.
        self._push_config = FcmPushClientConfig(
            abort_on_sequential_error_count=None,
            connection_retry_count=10,
        )

        self.credentials = get_cached_value('fcm_credentials')
        self.location_update_callbacks = []
        self._callbacks_lock = threading.Lock()
        self.pc = self._build_push_client()


    def _build_push_client(self):
        return FcmPushClient(
            self._on_notification,
            self._fcm_config,
            self.credentials,
            self._on_credentials_updated,
            config=self._push_config,
        )


    def _client_terminated(self):
        # The push client only reaches STOPPING/STOPPED via stop() or its own
        # _terminate() after a terminal error — never during normal startup
        # (CREATED -> STARTING_* -> STARTED), so this is a safe "is it dead?"
        # signal that won't false-trigger a restart while it is still connecting.
        return self.pc is not None and self.pc.run_state in (
            FcmPushClientRunState.STOPPING,
            FcmPushClientRunState.STOPPED,
        )


    def _teardown_dead_listener(self):
        # The dead client's listen/monitor tasks were cancelled and cannot be
        # revived, so stop its background loop and build a fresh client to start
        # cleanly on a new loop.
        self._listening = False
        old_loop = self._loop
        if old_loop and old_loop.is_running():
            old_loop.call_soon_threadsafe(old_loop.stop)
        self._loop = None
        self._loop_thread = None
        self.pc = self._build_push_client()


    def register_for_location_updates(self, callback):
        self._ensure_listening()

        with self._callbacks_lock:
            self.location_update_callbacks.append(callback)

        return self.credentials['fcm']['registration']['token']


    def _ensure_listening(self):
        # The FCM listener is a single shared connection. Start it exactly once,
        # even when many device-location requests register concurrently: starting
        # it more than once spawns multiple readers on the same socket and corrupts
        # the connection ("readexactly() called while another coroutine is already
        # waiting for incoming data"), after which every location request times out.
        # We must also restart it if the underlying push client has terminated;
        # otherwise a single terminal FCM error silently stops all location
        # updates and every request times out indefinitely.
        if self._listening and not self._client_terminated():
            return

        with self._start_lock:
            if self._listening and not self._client_terminated():
                return
            if self._client_terminated():
                self._teardown_dead_listener()
            self._start_listener_in_background()


    def unregister_for_location_updates(self, callback):
        # Callers must unregister once their request resolves; otherwise the shared
        # callback list grows without bound (every poll cycle registers one callback
        # per device) and each notification fans out to ever more dead callbacks.
        with self._callbacks_lock:
            try:
                self.location_update_callbacks.remove(callback)
            except ValueError:
                pass


    def stop_listening(self):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.pc.stop(), self._loop)
        self._listening = False


    def get_android_id(self):

        if self.credentials is None:
            return self._start_listener_in_background()

        return self.credentials['gcm']['android_id']


    # Define a callback function for handling notifications
    def _on_notification(self, obj, notification, data_message):

        # Check if the payload is present
        if 'data' in obj and 'com.google.android.apps.adm.FCM_PAYLOAD' in obj['data']:

            # Decode the base64 string
            base64_string = obj['data']['com.google.android.apps.adm.FCM_PAYLOAD']
            decoded_bytes = base64.b64decode(base64_string)

            # print("[FCMReceiver] Decoded FMDN Message:", decoded_bytes.hex())

            # Convert to hex string
            hex_string = binascii.hexlify(decoded_bytes).decode('utf-8')

            with self._callbacks_lock:
                callbacks = list(self.location_update_callbacks)
            for callback in callbacks:
                callback(hex_string)
        else:
            print("[FCMReceiver] Payload not found in the notification.")


    def _on_credentials_updated(self, creds):
        self.credentials = creds

        # Also store to disk
        set_cached_value('fcm_credentials', self.credentials)
        print("[FCMReceiver] Credentials updated.")


    async def _register_for_fcm(self):
        fcm_token = None

        # Register or check in with FCM and get the FCM token
        while fcm_token is None:
            try:
                fcm_token = await self.pc.checkin_or_register()
            except Exception as e:
                await self.pc.stop()
                print("[FCMReceiver] Failed to register with FCM. Retrying...")
                await asyncio.sleep(5)


    async def _register_for_fcm_and_listen(self):
        await self._register_for_fcm()
        # Start the FCM listener
        await self.pc.start()

    def _run_event_loop_in_thread(self):
        """Run the event loop in a background thread"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _start_listener_in_background(self):
        """Start FCM listener in a background thread with its own event loop"""
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_event_loop_in_thread, daemon=True)
        self._loop_thread.start()

        if self.credentials is None:
            # No cached credentials — full GCM registration needed
            temp_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(temp_loop)
            temp_loop.run_until_complete(self._register_for_fcm())
            temp_loop.close()
        else:
            # Cached credentials available — skip GCM check-in and use them directly
            self.pc.credentials = self.credentials
            print("[FCMReceiver] Using cached credentials, skipping GCM check-in.")

        # Now start the listener in the background loop
        asyncio.run_coroutine_threadsafe(self.pc.start(), self._loop)
        self._listening = True
        print("[FCMReceiver] Listening for notifications. This can take a few seconds...")

        return self.credentials['gcm']['android_id']


if __name__ == "__main__":
    receiver = FcmReceiver()
    print(receiver.get_android_id())
