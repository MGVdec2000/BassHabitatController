"""
Vision / tortoise detection module.

Primary method: OpenCV MOG2 background subtraction + largest-contour centroid.
The background model adapts over time so slow ambient changes are ignored while
the tortoise (the moving foreground object) is picked out.

Designed to be extensible: replace or augment ``detect()`` with a YOLO or
classifier-based detector without changing the calling interface in
``run_tracker.py``.

Camera open failures are retried with exponential backoff up to _MAX_RETRIES
times before the caller is notified.
"""

import logging
import time

import cv2

logger = logging.getLogger(__name__)

_INITIAL_RETRY_DELAY = 1.0   # seconds for first retry
_MAX_RETRIES = 5


class TortoiseTracker:
    """
    Opens the camera and detects the tortoise position in each frame.

    Parameters
    ----------
    config : pantilt.config.Config
    """

    def __init__(self, config):
        cam = config["camera"]
        self._index: int = int(cam.get("index", 0))
        self._width: int = int(cam.get("width", 640))
        self._height: int = int(cam.get("height", 480))
        self._fps: int = int(cam.get("fps", 15))
        self._conf_thresh: float = float(
            config["tracking"].get("confidence_threshold", 0.3)
        )

        self._cap: cv2.VideoCapture | None = None

        # MOG2 background subtractor – shadow detection off (cleaner mask)
        self._bg_sub = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=50, detectShadows=False
        )

        # Morphological kernel for mask cleanup
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    # ── Camera lifecycle ─────────────────────────────────────────────────────

    def start(self) -> bool:
        """Open the camera.  Returns True on success."""
        return self._open_camera()

    def stop(self) -> None:
        """Release the camera capture resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("Camera released.")

    # ── Frame acquisition ────────────────────────────────────────────────────

    def read_frame(self):
        """
        Read one frame from the camera.

        On failure the camera is re-opened and the read retried with backoff.
        Returns the frame (numpy array) or *None* if all retries fail.
        """
        if self._cap is None or not self._cap.isOpened():
            if not self._open_camera():
                return None

        delay = _INITIAL_RETRY_DELAY
        for attempt in range(_MAX_RETRIES):
            ret, frame = self._cap.read()
            if ret and frame is not None:
                return frame
            logger.warning(
                "Frame read failed (attempt %d/%d). Re-opening camera in %.1fs…",
                attempt + 1, _MAX_RETRIES, delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, 10.0)
            self._cap.release()
            self._cap = None
            if not self._open_camera():
                return None

        logger.error("Could not read frame after %d retries.", _MAX_RETRIES)
        return None

    # ── Detection ────────────────────────────────────────────────────────────

    def detect(self, frame):
        """
        Detect the tortoise in *frame*.

        Returns
        -------
        (cx, cy, confidence, bbox) where bbox = (x, y, w, h), or
        (None, None, 0.0, None) if nothing detected above the threshold.
        """
        # ── Background subtraction ──────────────────────────────────────────
        fg_mask = self._bg_sub.apply(frame)

        # ── Morphological cleanup (remove noise / fill gaps) ────────────────
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, self._kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, self._kernel)

        # ── Contour detection ────────────────────────────────────────────────
        contours, _ = cv2.findContours(
            fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None, None, 0.0, None

        # Largest contour is assumed to be the tortoise
        best = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(best)
        frame_area = float(frame.shape[0] * frame.shape[1])

        # Confidence: fraction of half the frame area occupied by the blob
        # (capped at 1.0).  Blobs covering < confidence_threshold of that
        # reference area are ignored.
        confidence = min(1.0, area / (frame_area * 0.5))
        if confidence < self._conf_thresh:
            return None, None, confidence, None

        x, y, w, h = cv2.boundingRect(best)
        cx = x + w // 2
        cy = y + h // 2
        return cx, cy, confidence, (x, y, w, h)

    # ── Annotation ───────────────────────────────────────────────────────────

    def annotate_frame(self, frame, cx: int, cy: int, confidence: float, bbox):
        """
        Draw bounding box, centroid marker, and confidence label on *frame*.
        Modifies frame in-place and returns it.
        """
        if bbox is not None:
            x, y, w, h = bbox
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)
            cv2.putText(
                frame,
                f"conf={confidence:.2f}",
                (x, max(y - 8, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
        return frame

    # ── Internal ─────────────────────────────────────────────────────────────

    def _open_camera(self) -> bool:
        delay = _INITIAL_RETRY_DELAY
        for attempt in range(1, _MAX_RETRIES + 1):
            cap = cv2.VideoCapture(self._index)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
                cap.set(cv2.CAP_PROP_FPS, self._fps)
                self._cap = cap
                logger.info(
                    "Camera /dev/video%d opened at %dx%d @ %d fps.",
                    self._index, self._width, self._height, self._fps,
                )
                return True
            logger.warning(
                "Camera open failed (attempt %d/%d). Retrying in %.1fs…",
                attempt, _MAX_RETRIES, delay,
            )
            cap.release()
            time.sleep(delay)
            delay = min(delay * 2, 10.0)
        logger.error(
            "Could not open camera /dev/video%d after %d attempts.",
            self._index, _MAX_RETRIES,
        )
        return False
