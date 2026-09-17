import json

from packages.evaluation.metrics import character_accuracy, detection_counts, iou


def test_one_to_one_detection_matching_and_json():
    truth = [{"class": "car", "bbox": [0, 0, 10, 10]}]
    predictions = [
        {"class": "car", "bbox": [0, 0, 10, 10]},
        {"class": "car", "bbox": [0, 0, 10, 10]},
    ]
    result = detection_counts(truth, predictions)
    assert result["car"] == {"tp": 1, "fp": 1, "fn": 0}
    assert json.loads(json.dumps(result)) == result
    assert iou([0, 0, 10, 10], [10, 10, 20, 20]) == 0


def test_plate_character_distance_counts_missing_and_wrong_characters():
    assert character_accuracy("KA01AB1234", "KA01AB1234") == 1
    assert character_accuracy("KA01AB1234", "KA01AB123") == 0.9
    assert character_accuracy("KA01AB1234", "") == 0
