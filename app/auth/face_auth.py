import os
import pickle
import threading
import time
from datetime import datetime

import face_recognition
from flask import current_app
from flask_login import login_user

from app.database.connection_manager import get_master_connection
from app.auth.service import get_user_by_id, log_login_attempt


FACE_CACHE_TTL_SECONDS = 60
_FACE_CACHE_LOCK = threading.Lock()
_FACE_CACHE = {
    "loaded_at": 0,
    "rows": None,
}


def clear_face_encoding_cache():
    with _FACE_CACHE_LOCK:
        _FACE_CACHE["loaded_at"] = 0
        _FACE_CACHE["rows"] = None


def ensure_user_face_dir(user_id):
    user_dir = os.path.join(current_app.static_folder, "face_data", str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def create_face_encoding_from_loaded_image(image, upsample=1):
    face_locations = face_recognition.face_locations(
        image,
        number_of_times_to_upsample=upsample,
        model="hog"
    )

    if not face_locations:
        return None, "No face detected."

    face_locations = sorted(
        face_locations,
        key=lambda box: (box[2] - box[0]) * (box[1] - box[3]),
        reverse=True
    )

    largest_face = face_locations[0]

    if len(face_locations) > 1:
        first_area = (face_locations[0][2] - face_locations[0][0]) * (face_locations[0][1] - face_locations[0][3])
        second_area = (face_locations[1][2] - face_locations[1][0]) * (face_locations[1][1] - face_locations[1][3])

        if second_area > first_area * 0.45:
            return None, "Multiple faces detected."

    encodings = face_recognition.face_encodings(
        image,
        known_face_locations=[largest_face],
        num_jitters=1
    )

    if not encodings:
        return None, "Face encoding could not be created."

    return encodings[0], None


def create_face_encoding_from_image(image_path):
    image = face_recognition.load_image_file(image_path)
    return create_face_encoding_from_loaded_image(image, upsample=1)


def create_face_encoding_from_uploaded_file(uploaded_file):
    uploaded_file.stream.seek(0)
    image = face_recognition.load_image_file(uploaded_file.stream)
    return create_face_encoding_from_loaded_image(image, upsample=0)


def save_face_encoding_to_db(user_id, image_path, encoding):
    conn = get_master_connection()
    cursor = conn.cursor()

    encoding_bytes = pickle.dumps(encoding)

    cursor.execute("""
        INSERT INTO UserFaceEncodings (
            user_id, face_image_path, encoding_data
        )
        VALUES (?, ?, ?)
    """, user_id, image_path, encoding_bytes)

    conn.commit()
    conn.close()
    clear_face_encoding_cache()


def register_face_from_uploaded_file(user_id, uploaded_file):
    user_dir = ensure_user_face_dir(user_id)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"face_{timestamp}.jpg"
    file_path = os.path.join(user_dir, filename)

    uploaded_file.save(file_path)

    if not os.path.exists(file_path):
        return False, "Face image file could not be saved."

    encoding, error = create_face_encoding_from_image(file_path)
    if error:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return False, error

    db_path = f"face_data/{user_id}/{filename}"
    save_face_encoding_to_db(user_id, db_path, encoding)

    return True, "Face registered successfully."


def get_all_face_encodings():
    now = time.time()
    with _FACE_CACHE_LOCK:
        cached_rows = _FACE_CACHE["rows"]
        cache_age = now - _FACE_CACHE["loaded_at"]
        if cached_rows is not None and cache_age < FACE_CACHE_TTL_SECONDS:
            return cached_rows

    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, encoding_data
        FROM UserFaceEncodings
    """)

    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        try:
            encoding = pickle.loads(row.encoding_data)
            results.append({
                "user_id": row.user_id,
                "encoding": encoding
            })
        except Exception:
            continue

    with _FACE_CACHE_LOCK:
        _FACE_CACHE["loaded_at"] = now
        _FACE_CACHE["rows"] = results

    return results


def distance_to_confidence(distance):
    if distance is None:
        return 0

    if distance >= 0.60:
        return 0

    return max(0, min(100, int((1 - (distance / 0.60)) * 100)))


def match_face_from_uploaded_file(uploaded_file, tolerance=0.50):
    unknown_encoding, error = create_face_encoding_from_uploaded_file(uploaded_file)

    if error:
        return None, error, None, None

    known_faces = get_all_face_encodings()

    if not known_faces:
        return None, "No registered face data found in the system.", None, None

    known_encodings = [item["encoding"] for item in known_faces]
    face_distances = face_recognition.face_distance(known_encodings, unknown_encoding)

    if len(face_distances) == 0:
        return None, "No face data found.", None, None

    best_index = int(face_distances.argmin())
    best_user_id = known_faces[best_index]["user_id"]
    best_distance = float(face_distances[best_index])

    if best_distance > tolerance:
        return None, "Face not recognized.", best_distance, distance_to_confidence(best_distance)

    user = get_user_by_id(best_user_id)

    if not user:
        return None, "Matched user not found or inactive.", best_distance, distance_to_confidence(best_distance)

    return user, None, best_distance, distance_to_confidence(best_distance)


def perform_face_login(uploaded_file):
    user, error, distance, confidence = match_face_from_uploaded_file(uploaded_file)

    if error:
        return False, {
            "message": error,
            "distance": distance,
            "confidence": confidence
        }

    login_user(user)
    log_login_attempt(user.id, user.org_id, "face", "success")

    return True, {
        "user": user,
        "distance": distance,
        "confidence": confidence
    }


def get_face_record_by_user_id(user_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT TOP 1 id, user_id, face_image_path, encoding_data, created_at
        FROM UserFaceEncodings
        WHERE user_id = ?
        ORDER BY id DESC
    """, user_id)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row.id,
        "user_id": row.user_id,
        "face_image_path": row.face_image_path,
        "created_at": row.created_at
    }


def delete_face_by_user_id(user_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT face_image_path
        FROM UserFaceEncodings
        WHERE user_id = ?
    """, user_id)

    rows = cursor.fetchall()

    cursor.execute("DELETE FROM UserFaceEncodings WHERE user_id = ?", user_id)
    conn.commit()
    conn.close()
    clear_face_encoding_cache()

    for row in rows:
        if row.face_image_path:
            abs_path = os.path.join(current_app.static_folder, row.face_image_path.replace("/", os.sep))
            try:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            except Exception:
                pass

    return True
