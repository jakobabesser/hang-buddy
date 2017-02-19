################################################################################
# Copyright (C) 2012-2013 Leap Motion, Inc. All rights reserved.               #
# Leap Motion proprietary and confidential. Not for distribution.              #
# Use subject to the terms of the Leap Motion SDK Agreement available at       #
# https://developer.leapmotion.com/sdk_agreement, or another agreement         #
# between Leap Motion and you, your company or other organization.             #
################################################################################



import Leap, sys, thread, time
from Leap import CircleGesture, KeyTapGesture, ScreenTapGesture, SwipeGesture
import rtmidi
import time
import numpy as np


class IHDController(Leap.Listener):
    """ Main controller class """

    def __init__(self):
        Leap.Listener.__init__(self)

        self.player = IHDPlayer(self)
        self.gesture_detector = IHDGestureDetector(self)

        self.silence_in_frames = 2
        self.silent_frames = 0

        self.start_time = time.time()

        self.tempo_bpm = 110.
        self.numerator = 8

        self.beat_duration = 60/self.tempo_bpm
        self.beat_idx = 0
        self.prev_time_mod = 0
        self.beat_times_in_bar = np.arange(self.numerator*2)*self.beat_duration/2.
        self.beats_passed = np.zeros(self.numerator*2, dtype=bool)

        self.start_time_first_beat = 2
        self.metronome_started = False

        self.last_bar_start_time = None

        self.user_played_notes = []

        self.player.active_player = 'COMPUTER'

        # self.detection_method = 'key_tap'
        self.detection_method = 'manual'

        self.bar_number = -1

        self.num_random_notes = 5




    def on_init(self, controller):
        print "Initialized"

    def on_connect(self, controller):
        print "Connected"

        # Enable gestures
        # controller.enable_gesture(Leap.Gesture.TYPE_CIRCLE)
        # controller.enable_gesture(Leap.Gesture.TYPE_KEY_TAP)
        # controller.enable_gesture(Leap.Gesture.TYPE_SCREEN_TAP)
        controller.enable_gesture(Leap.Gesture.TYPE_SWIPE)

        # todo place parameters to class arguments
        controller.config.set("Gesture.KeyTap.MinDownVelocity", 20)# 40.0)
        controller.config.set("Gesture.KeyTap.HistorySeconds", .1) #.2)
        controller.config.set("Gesture.KeyTap.MinDistance", 5)#1.0)

        controller.config.set("Gesture.Swipe.MinLength", 300.0)
        controller.config.set("Gesture.Swipe.MinVelocity", 750)

        # controller.config.save()

    def on_disconnect(self, controller):
        # Note: not dispatched when running in a debugger.
        print "Disconnected"

    def on_exit(self, controller):
        print "Exited"

    def on_frame(self, controller):
        """ Callback which is called every frame with leap motion controller data """

        curr_time = time.time()

        # get current data from motion sensor
        frame = controller.frame()

        # hand stroke detection
        command = self.gesture_detector.analyze_frame(frame, curr_time)

        if command is not None:
            self.player.play(command)

        # start metronome after initial delay
        if curr_time > self.start_time_first_beat and not self.metronome_started:
            print('METRONOME STARTED')
            self.metronome_started = True
            self.metronome_start_time = curr_time

        if self.metronome_started:
            if self.last_bar_start_time is not None:
                curr_time_in_beat = curr_time - self.last_bar_start_time
                beats_passed = self.beat_times_in_bar < curr_time_in_beat
                self.beats_passed[beats_passed] = True

            # self.beat_times_in_bar = np.arange(self.numerator) * self.beat_duration / 2.
            # self.beats_passed = np.zeros(self.numerator, dtype=bool)

        if self.metronome_started:
            self.check_for_beat()

        self.player.update()

    def quantize_user_played_notes(self):
        self.quant_mat = np.zeros((7, self.numerator*2))
        for note in self.user_played_notes:
            # print("%f mod %f = %f" % (note[0], self.beat_duration, note[0] / self.beat_duration))
            self.quant_mat[note[1], int(note[0] / (.5*self.beat_duration))] = 1

        # modify rhythm from user
        nr, nc = self.quant_mat.shape
        for i in range(self.num_random_notes):
            r = int(np.floor(np.random.random()*nr))
            c = int(np.floor(np.random.random()*nc))
            self.quant_mat[r, c] = np.logical_not(self.quant_mat[r, c])

    def play_click(self):
        """ Play click sound depending on beat position """
        command = IHDPlayCommand(instrument='click', level=0.8)
        if self.beat_idx == 0:
            self.bar_number += 1
            self.last_bar_start_time = time.time()
            self.beats_passed = np.zeros(self.numerator*2, dtype=bool)
            # switch between user and computer
            if self.bar_number % 2 == 1:
                self.player.active_player = 'USER'
                self.user_played_notes = []
            else:
                self.player.active_player = 'COMPUTER'
                self.quantize_user_played_notes()
            print('%s PLAYS NOW!' % self.player.active_player)

            command.note_id = 0
        else:
            command.note_id = 1

        self.player.play(command)

        self.beat_idx += 1
        self.beat_idx %= self.numerator

    def check_for_beat(self):
        """ Check if current frame time is close to beat time and play click sound if so"""
        curr_time = time.time() - self.metronome_start_time
        curr_time_mod = curr_time % self.beat_duration
        if curr_time_mod < self.prev_time_mod:
            self.play_click()
        self.prev_time_mod = curr_time_mod


class IHDHandMemory:
    """ Class implements memory over hand position to detect hand strokes from tracking data """

    def __init__(self):
        self.memory = None
        self.delta_height = None
        self.delta_height_border = None
        self.reset_all()

    def reset_all(self):
        self.memory = {}
        self.delta_height = 15
        self.delta_height_border = -3

    def check_for_hand_stroke(self, _id, position, curr_frame_id):
        """ Check current and previous hand positions to detect hand stroke"""
        height = position[1]
        check = False

        # check if hand with ID is already saved in the hand memory
        if _id not in self.memory:
            # create new entry for new hand ID
            self.memory[_id] = {'prev_height': height,
                                'downwards': False,
                                'prev_frame_id': curr_frame_id,
                                'hit_detected': False,
                                'prev_position': position,
                                'min_movement_distance_check': False}
        else:
            # update existing entry
            self.memory[_id]['prev_frame_id'] = curr_frame_id
            # get direction of movement (upwards / downwards)
            self.memory[_id]['downwards'] = height < self.memory[_id]['prev_height']
            if self.memory[_id]['downwards']:
                # check height distance since last frame
                delta_height = position[1] - self.memory[_id]['prev_position'][1]
                if delta_height < self.delta_height_border:
                    self.memory[_id]['min_movement_distance_check'] = True
            else:
                # reset
                self.reset_id(_id, height)
            # save current hand position for next frame
            self.memory[_id]['prev_position'] = position

        # detect hand stroke
        if self.memory[_id]['prev_height'] - height > self.delta_height and \
           not self.memory[_id]['hit_detected'] and \
           self.memory[_id]['min_movement_distance_check']:
            check = True
            # print('Bam! %d ' % curr_frame_id)

            self.memory[_id]['prev_height'] = height
            self.memory[_id]['hit_detected'] = True

        # remove old entries
        self.remove_old_entries(curr_frame_id)
        return check

    def remove_old_entries(self, curr_frame_id):
        """ Remove "old" hands, whose IDs were not tracked in the previous frame
            (if hand tracking is interrupted, hand gets new ID, old one gets obsolete
        """
        for _key in self.memory.keys():
            if curr_frame_id - self.memory[_key]['prev_frame_id'] > 1:
                self.memory.pop(_key)

    def reset_id(self, _id, height):
        """ Reset memory entry (after hand starts moving upwards) """
        self.memory[_id]['prev_height'] = height
        self.memory[_id]['hit_detected'] = False


class IHDTools:
    """ Additional tools """

    def __init__(self):
        pass

    @staticmethod
    def get_drum_positions_hexagon_layout(radius):
        """ Hexagon drum layout (similar to Hang drum)

                    P7

              P5          P6
                    P1

              P3          P4

                    P2
        """
        radius_norm = np.sqrt(3) / 2 * radius
        radius_norm_1_2 = radius_norm / 2.
        hexagon_positions = np.array(((0, 0),
                                      (0, radius_norm),
                                      (-radius_norm, radius_norm_1_2),
                                      (radius_norm, radius_norm_1_2),
                                      (-radius_norm, -radius_norm_1_2),
                                      (radius_norm, -radius_norm_1_2),
                                      (0, -radius_norm)))

        return hexagon_positions

    @staticmethod
    def get_pitches_for_scale(scale):
        if scale == 'ionian':
            return np.arange(36, 43)
        elif scale == 'ionian_inv':
            return np.arange(42, 35, -1)
        elif scale == 'random':
            pitches = np.arange(36, 42)
            np.random.shuffle(pitches)
            return pitches
        else:
            raise Exception('Undefined scale')


class IHDGestureDetector:
    """ Main class to detect drumming gestures based on LeapMotion controller data """

    def __init__(self, controller):
        self.start_time = time.time()
        self.last_event_time_sec = 0
        self.reset_after_time_sec = 2
        self.frame_id = 0
        self.controller = controller
        self.hand_memory = IHDHandMemory()

        self.hexagon_positions_radius = 100
        self.hexagon_positions = IHDTools.get_drum_positions_hexagon_layout(self.hexagon_positions_radius)

        self.swipe_min_abs_dx = 80
        self.last_swipe_detected_sec = 0
        self.min_time_between_swipes_sec = .5

        self.state_names = ['STATE_INVALID', 'STATE_START', 'STATE_UPDATE', 'STATE_END']

    def analyze_frame(self, frame, curr_time):
        """ Analyze current frame for relevant gestures from motion capture device """
        self.update_time(curr_time)

        self.detect_swipe_gesture(frame)

        hand_stroke_position = self.detect_hand_stroke(frame)
        command = None

        # if hand stroke was detected
        if hand_stroke_position is not None:
            self.last_event_time_sec = curr_time
            command = IHDPlayCommand(note_id=self.stroke_position_to_note_id(hand_stroke_position),
                                     level=1)

        self.frame_id += 1

        return command

    def detect_swipe_gesture(self, frame):
        """ Customized function to detect swipe gestures of both hands in both directions (right / left) """

        for gesture in frame.gestures():

            if gesture.type == Leap.Gesture.TYPE_SWIPE:

                if time.time() - self.last_swipe_detected_sec > self.min_time_between_swipes_sec:

                    swipe = SwipeGesture(gesture)

                    start_position = swipe.start_position
                    position = swipe.position

                    dx = start_position[0] - position[0]

                    is_left_hand = swipe.pointable.hand.is_left

                    swipe_is_rightwards = dx < 0
                    if abs(dx) > self.swipe_min_abs_dx:
                        self.last_swipe_detected_sec = time.time()  # todo replace by time stamp from main class

                        if not is_left_hand:
                            self.controller.player.next_scale(next_=swipe_is_rightwards)

                        # print('Swipe detected (dx = %f), direction = %s, hand = %s' % (dx,
                        #                                                                'right' if swipe_is_rightwards else 'left',
                        #                                                                'left' if is_left_hand else 'right'))

    def detect_hand_stroke(self, frame):
        """ Use internal hand memory to detect hand strokes """
        hand_stroke_position = None

        # check that at least one hand is in the frame
        hands = frame.hands
        if len(hands) > 0:
            for hand in hands:
                _id = hand.id
                position = hand.palm_position

                if self.hand_memory.check_for_hand_stroke(_id, position, self.frame_id):
                    hand_stroke_position = position

        return hand_stroke_position

    def update_time(self, curr_time):
        # check for hand memory reset
        if curr_time - self.last_event_time_sec > self.reset_after_time_sec:
            self.hand_memory.reset_all()
            self.last_event_time_sec = curr_time

    def stroke_position_to_note_id(self, position):
        """ Convert spatial position into drum number based on hexagon drum layout
        Args:
            position (tuple): Spatial hand_position (x, y, z)
        Returns
            drum_id
            """
        curr_pos = np.array((position[0], position[2]))

        # nearest neighbor search
        dist = np.sqrt(np.sum(np.square(self.hexagon_positions - curr_pos), axis=1))

        drum_id = np.argmin(dist)

        self.controller.user_played_notes.append((time.time() - self.controller.last_bar_start_time, drum_id))

        return drum_id


class IHDPlayCommand:

    def __init__(self, note_id=None, level=None, instrument='drum'):
        self.note_id = note_id
        self.level = level
        self.instrument = instrument


class IHDPlayer:

    def __init__(self, controller):
        self.controller = controller

        self.midi_out = rtmidi.MidiOut()
        available_ports = self.midi_out.get_ports()

        if available_ports:
            self.midi_out.open_port(0)
        else:
            self.midi_out.open_virtual_port("virtual_hand_drum")

        self.scale_id = 0
        self.scales = ['ionian', 'ionian_inv', 'random']
        self.num_scales = len(self.scales)
        self.active_player = None

    def drum_id_to_pitch(self, instrument, drum_id):
        if instrument == 'drum':
            pitches = IHDTools.get_pitches_for_scale(self.scales[self.scale_id])
        elif instrument == 'click':
            pitches = np.array((48, 49))
        else:
            raise Exception('Non-valid instrument')
        return pitches[drum_id]

    def update(self):

        if self.active_player == "COMPUTER":
            beats_passed = np.where(self.controller.beats_passed)[0]
            if len(beats_passed) > 0:
                last_beat_passed = beats_passed[-1]
                active_pitches = np.where(self.controller.quant_mat[:, last_beat_passed])[0]
                if len(active_pitches) > 0:
                    for note_id in active_pitches:
                        command = IHDPlayCommand(note_id, 1, instrument='drum')
                        self.controller.player.play(command)
                        self.controller.quant_mat[note_id, last_beat_passed] = False

    def next_scale(self, next_=True):
        if next_:
            if self.scale_id < self.num_scales - 1:
                self.change_scale(self.scale_id + 1)
            else:
                self.change_scale(0)
        else:
            if self.scale_id > 0:
                self.change_scale(self.scale_id - 1)
            else:
                self.change_scale(self.num_scales - 1)

    def change_scale(self, scale_id):
        """ Change internal scale to change mapping from note ids to pitches """
        self.scale_id = scale_id
        print('Changed scale to %s' % self.scales[self.scale_id])

    def play(self, command):
        """ Translate instrument, drum_id, and level to MIDI note event """
        pitch = self.drum_id_to_pitch(command.instrument, command.note_id)
        velocity = int(122.*command.level)
        # todo remove
        if command.instrument == 'click':
            velocity = 100
        self.midi_out.send_message([0x90, pitch, velocity])


def main():

    # Create a sample listener and controller
    listener = IHDController()
    controller = Leap.Controller()

    # Have the sample listener receive events from the controller
    controller.add_listener(listener)

    # Keep this process running until Enter is pressed
    print "Press Enter to quit..."
    try:
        sys.stdin.readline()
    except KeyboardInterrupt:
        pass
    finally:
        # Remove the sample listener when done
        controller.remove_listener(listener)

if __name__ == "__main__":
    main()
