from collections import deque
from scipy.optimize import linear_sum_assignment
import numpy as np
from model import ModelWrapper
from filterpy.kalman import KalmanFilter, ExtendedKalmanFilter, EnsembleKalmanFilter
from filterpy.common import Q_discrete_white_noise
import seaborn as sns
import itertools


class Tracker:
    def __init__(self, center, state_noise=1.0, r_scale=1.0, q_var=1.0, color=(255, 255, 255)):
        self.detection = center
        self.color = color
        self.filter = KalmanFilter(dim_x=4, dim_z=2)

        center = self.detection
        self.filter.x = np.array([center[0], 0, center[1], 0])

        self.dt = 1.0

        self.filter.F = np.array([[1, self.dt, 0, 0],
                                  [0, 1, 0, 0],
                                  [0, 0, 1, self.dt],
                                  [0, 0, 0, 1]])

        self.filter.H = np.array([[1, 0, 0, 0],
                                  [0, 0, 1, 0]])

        self.filter.P *= state_noise
        self.filter.R = np.diag(np.ones(2)) * state_noise * r_scale
        self.filter.Q = Q_discrete_white_noise(dim=2, dt=self.dt, var=q_var, block_size=2)

        self.id = 0
        self.hits = 0
        self.no_losses = 0

    def update_state(self, detection):
        self.detection = detection
        center = detection
        self.filter.predict()
        self.filter.update(center)

    def predict_only(self):
        self.filter.predict()

    def get_state(self):
        detection = {'detection': [self.filter.x[0], self.filter.x[2]], 'color': self.color}
        return detection


class Tracking:
    def __init__(self, state_noise=1.0, r_scale=1.0, q_var=1.0, iou_threshold=0.3, max_age=4, min_hits=1):
        # Global variables to be used by funcitons of VideoFileClop
        self.state_noise = state_noise
        self.r_scale = r_scale
        self.q_var = q_var
        self.iou_threshold = iou_threshold
        self.frame_count = 0  # frame counter
        self.max_age = max_age  # no.of consecutive unmatched detection before a track is deleted
        self.min_hits = min_hits  # no. of consecutive matches needed to establish a track
        self.tracker_list = list()  # list for trackers
        self.tracker_palette = itertools.cycle(sns.color_palette())

    def assign_detections_to_trackers(self, trackers, detections, iou_threshold=20):
        """
        From current list of trackers and new detections, output matched detections,
        unmatchted trackers, unmatched detections.
        """

        dist_mat = np.zeros((len(trackers), len(detections)), dtype=np.float32)

        for tracker_index, tracker in enumerate(trackers):
            tracker_box = tracker.get_state()['detection']
            # print(tracker_box)
            for detection_index, detection in enumerate(detections):
                detection_box = detection
                # dist_mat[tracker_index, detection_index] = tracker_box.get_iou(detection_box)

                dist_mat[tracker_index, detection_index] = \
                    np.sqrt(np.power(np.array(tracker_box) - np.array(detection_box), 2).sum())

        row_ind, col_ind = linear_sum_assignment(dist_mat)

        unmatched_trackers = list()
        unmatched_detections = list()

        for tracking_index, tracker in enumerate(trackers):
            if tracking_index not in row_ind:
                unmatched_trackers.append(tracking_index)

        for detection_index, detection in enumerate(detections):
            if detection_index not in col_ind:
                unmatched_detections.append(detection_index)

        matches = list()

        for m in zip(row_ind, col_ind):
            if dist_mat[m[0], m[1]] > iou_threshold:
                unmatched_trackers.append(m[0])
                unmatched_detections.append(m[1])
            else:
                matches.append(np.array(m).reshape(1, 2))

        if len(matches) == 0:
            matches = np.empty((0, 2), dtype=int)
        else:
            matches = np.concatenate(matches, axis=0)

        return matches, np.array(unmatched_detections), np.array(unmatched_trackers)

    def track(self, detections):
        """
        Pipeline function for detection and tracking
        """
        self.frame_count += 1

        if len(self.tracker_list) == 0 and len(detections) == 0:
            return list()

        trackers = list()

        if len(self.tracker_list) > 0:
            for tracker in self.tracker_list:
                trackers.append(tracker)

        matched, unmatched_detections, unmatched_trackings = \
            self.assign_detections_to_trackers(
                trackers=trackers, detections=detections, iou_threshold=self.iou_threshold
            )

        # Deal with matched detections
        if matched.size > 0:
            for tracking_index, detection_index in matched:
                detection = detections[detection_index]
                tmp_tracker = self.tracker_list[tracking_index]
                tmp_tracker.update_state(detection)
                tmp_tracker.hits += 1
                tmp_tracker.no_losses = 0

        # Deal with unmatched detections
        if len(unmatched_detections) > 0:
            for index in unmatched_detections:
                detection = detections[index]
                new_tracker = Tracker(
                    detection, state_noise=self.state_noise,
                    r_scale=self.r_scale, q_var=self.q_var,
                    color=(np.array(next(self.tracker_palette)) * 255).astype(np.int)
                )

                new_tracker.predict_only()
                self.tracker_list.append(new_tracker)

        # Deal with unmatched tracks
        if len(unmatched_trackings) > 0:
            for tracking_index in unmatched_trackings:
                tmp_tracker = self.tracker_list[tracking_index]
                tmp_tracker.no_losses += 1
                tmp_tracker.predict_only()

        # The list of tracks to be annotated
        good_detections = list()

        for tracker in self.tracker_list:
            if tracker.hits >= self.min_hits and tracker.no_losses <= self.max_age:
                good_detections.append(tracker.get_state())

        self.tracker_list = [x for x in self.tracker_list if x.no_losses <= self.max_age]

        return good_detections


class ModelTracker:
    def __init__(self, detection, color=(255, 0, 0)):
        self.queue = deque()
        self.color = color
        self.queue.append(detection)
        file_path_pattern = '/home/marcus/data/sber/lr_len_{}.pkl'
        # file_path_pattern = 'lr_len_{}.pkl'
        self.lengths = (2, 4, 8, 16, 32, 64)
        self.models = [ModelWrapper(file_path_pattern, length) for length in self.lengths]
        self.hits = 0
        self.no_losses = 0

    def _predict_next_detection(self):
        if len(self.queue) == 1:
            return self.queue[-1]

        current_model = self._choose_right_model()
        return current_model.predict(self.queue)

    def _choose_right_model(self):
        right_index = 0
        for index, model_length in enumerate(self.lengths):
            if model_length <= len(self.queue):
                right_index = index
            else:
                break
        return self.models[right_index]

    def update(self, detection):
        self.queue.append(detection)

    def update_with_estimation(self):
        next_prediction = self._predict_next_detection()
        self.queue.append(next_prediction)

    def get_state(self):
        return {'detection': self.queue[-1], 'color': self.color}

    def get_estimation(self):
        return self._predict_next_detection()


class ModelTracking:
    def __init__(self, iou_threshold=0.3, max_age=4, min_hits=1):
        self.iou_threshold = iou_threshold
        self.frame_count = 0  # frame counter
        self.max_age = max_age  # no.of consecutive unmatched detection before a track is deleted
        self.min_hits = min_hits  # no. of consecutive matches needed to establish a track
        self.tracker_list = list()  # list for trackers
        self.tracker_palette = itertools.cycle(sns.color_palette())

    def assign_detections_to_trackers(self, trackers, detections, iou_threshold=20):
        """
        From current list of trackers and new detections, output matched detections,
        unmatchted trackers, unmatched detections.
        """

        dist_mat = np.zeros((len(trackers), len(detections)), dtype=np.float32)

        for tracker_index, tracker in enumerate(trackers):
            tracker_box = tracker.get_estimation()

            for detection_index, detection in enumerate(detections):
                detection_box = detection

                dist_mat[tracker_index, detection_index] = \
                    np.sqrt(np.power(np.array(tracker_box) - np.array(detection_box), 2).sum())

        row_ind, col_ind = linear_sum_assignment(dist_mat)

        unmatched_trackers = list()
        unmatched_detections = list()

        for tracking_index, tracker in enumerate(trackers):
            if tracking_index not in row_ind:
                unmatched_trackers.append(tracking_index)

        for detection_index, detection in enumerate(detections):
            if detection_index not in col_ind:
                unmatched_detections.append(detection_index)

        matches = list()

        for m in zip(row_ind, col_ind):
            if dist_mat[m[0], m[1]] > iou_threshold:
                unmatched_trackers.append(m[0])
                unmatched_detections.append(m[1])
            else:
                matches.append(np.array(m).reshape(1, 2))

        if len(matches) == 0:
            matches = np.empty((0, 2), dtype=int)
        else:
            matches = np.concatenate(matches, axis=0)

        return matches, np.array(unmatched_detections), np.array(unmatched_trackers)

    def track(self, detections):
        """
        Pipeline function for detection and tracking
        """
        self.frame_count += 1

        if len(self.tracker_list) == 0 and len(detections) == 0:
            return list()

        trackers = list()

        if len(self.tracker_list) > 0:
            for tracker in self.tracker_list:
                trackers.append(tracker)

        matched, unmatched_detections, unmatched_trackings = \
            self.assign_detections_to_trackers(
                trackers=trackers, detections=detections, iou_threshold=self.iou_threshold
            )

        # Deal with matched detections
        if matched.size > 0:
            for tracking_index, detection_index in matched:
                detection = detections[detection_index]
                tmp_tracker = self.tracker_list[tracking_index]
                tmp_tracker.update(detection)
                tmp_tracker.hits += 1
                tmp_tracker.no_losses = 0

        # Deal with unmatched detections
        if len(unmatched_detections) > 0:
            for index in unmatched_detections:
                detection = detections[index]
                new_tracker = ModelTracker(
                    detection, color=(np.array(next(self.tracker_palette)) * 255).astype(np.int)
                )
                self.tracker_list.append(new_tracker)

        # Deal with unmatched tracks
        if len(unmatched_trackings) > 0:
            for tracking_index in unmatched_trackings:
                tmp_tracker = self.tracker_list[tracking_index]
                tmp_tracker.no_losses += 1
                tmp_tracker.update_with_estimation()

        # The list of tracks to be annotated
        good_detections = list()

        for tracker in self.tracker_list:
            if tracker.hits >= self.min_hits and tracker.no_losses <= self.max_age:
                good_detections.append(tracker.get_state())

        self.tracker_list = [x for x in self.tracker_list if x.no_losses <= self.max_age]

        return good_detections


if __name__ == "__main__":
    uber_tracker = ModelTracker(
        [0, 100],
    )

    print(uber_tracker.get_estimation())

    for measurement in (
            [0, 98.0],
            [5.0, 120.0],
            [7.0, 144.3],
            [8.0, 161.0],
            [8.0, 190.0],
            [8.0, 190.0],
            [8.0, 190.0],
    ):
        uber_tracker.update(detection=measurement)
        print(uber_tracker.get_state())
        print()

    print('\n\n\n')

    for i in range(10):
        uber_tracker.update_with_estimation()
        print(uber_tracker.get_state())
        print()
