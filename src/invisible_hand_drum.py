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


class HandMemory:
    """ Class implements memory over hand position to detect hand strokes from tracking data """

    def __init__(self):
        self.memory = None
        self.delta_height = None
        self.delta_height_border = None
        self.reset_all()

    def reset_all(self):
        # print('RESET ALL')
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


class VirtualHangDrum(Leap.Listener):

    def __init__(self):
        Leap.Listener.__init__(self)

        self.player = Player()

        self.midi_out = rtmidi.MidiOut()
        available_ports = self.midi_out.get_ports()

        if available_ports:
            self.midi_out.open_port(0)
        else:
            self.midi_out.open_virtual_port("hangbuddy")

        self.silence_in_frames = 2
        self.silent_frames = 0

        self.start_time = time.time()
        self.last_event_time = 0
        self.reset_after_time = 2

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

        self.click_velocity = 100
        self.click_pitch_beat_one = 48
        self.click_pitch_beat_other = 49

        self.player = 'COMPUTER'

        # self.detection_method = 'key_tap'
        self.detection_method = 'manual'
        self.hand_memory = HandMemory()

        self.bar_number = -1

        self.num_random_notes = 5

        # heptagon layout for Hang drum
        """
                    P7

              P5          P6
                    P1

              P3          P4

                    P2

        """

        self.heptagon_positions_radius = 100
        r1 = self.heptagon_positions_radius
        r2 = np.sqrt(3)/2*r1
        r1_2 = r1/2.

        self.heptagon_positions_pitches = np.arange(36, 43)
        self.heptagon_positions = np.array(((0, 0),
                                            (0, r1),
                                            (-r2, r1_2),
                                            (r2, r1_2),
                                            (-r2, -r1_2),
                                            (r2, -r1_2),
                                            (0, -r1)))

        self.heptagon_positions = np.hstack((self.heptagon_positions, self.heptagon_positions_pitches[:, np.newaxis]))

        self.frame_id = 0

    def on_init(self, controller):
        print "Initialized"

    def on_connect(self, controller):
        print "Connected"

        # Enable gestures
        # controller.enable_gesture(Leap.Gesture.TYPE_CIRCLE)
        controller.enable_gesture(Leap.Gesture.TYPE_KEY_TAP)
        # controller.enable_gesture(Leap.Gesture.TYPE_SCREEN_TAP)
        # controller.enable_gesture(Leap.Gesture.TYPE_SWIPE)

        # print('controller.config.set("Gesture.KeyTap.MinDownVelocity"' + str(controller.config.get("Gesture.KeyTap.MinDownVelocity")))
        # print('controller.config.set("Gesture.KeyTap.HistorySeconds"' + str(controller.config.get("Gesture.KeyTap.HistorySeconds")))
        # print('controller.config.set("Gesture.KeyTap.MinDistance"' + str(controller.config.get("Gesture.KeyTap.MinDistance")))

        controller.config.set("Gesture.KeyTap.MinDownVelocity", 20)# 40.0)
        controller.config.set("Gesture.KeyTap.HistorySeconds", .1) #.2)
        controller.config.set("Gesture.KeyTap.MinDistance", 5)#1.0)
        # controller.config.save()

    def on_disconnect(self, controller):
        # Note: not dispatched when running in a debugger.
        print "Disconnected"

    def on_exit(self, controller):
        print "Exited"

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

        #
        # print(self.user_played_notes)
        # print(self.quant_mat)


    def play_click(self):
        """ Play click sound depending on beat position """
        if self.beat_idx == 0:
            self.bar_number += 1
            self.last_bar_start_time = time.time()
            self.beats_passed = np.zeros(self.numerator*2, dtype=bool)
            # switch between user and computer
            if self.bar_number % 2 == 1:
                self.player = 'USER'
                self.user_played_notes = []
            else:
                self.player = 'COMPUTER'
                self.quantize_user_played_notes()
            print('%s PLAYS NOW!' % self.player)

            self.play_note(self.click_pitch_beat_one, self.click_velocity)
            # print('BAR NUMBER ' + str(self.bar_number))
        else:
            self.play_note(self.click_pitch_beat_other, self.click_velocity)
        self.beat_idx += 1
        self.beat_idx %= self.numerator

    def check_for_beat(self):
        """ Check if current frame time is close to beat time and play click sound if so"""
        curr_time = time.time() - self.metronome_start_time
        curr_time_mod = curr_time % self.beat_duration
        if curr_time_mod < self.prev_time_mod:
            self.play_click()
        self.prev_time_mod = curr_time_mod

    def on_frame(self, controller):
        """ Callback which is called every frame with controller data """

        # reset hand memory after a while if nothing happens
        curr_time = time.time()
        if curr_time - self.last_event_time > self.reset_after_time:
            self.hand_memory.reset_all()
            self.last_event_time = curr_time

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

        # Get the most recent frame and report some basic information
        frame = controller.frame()

        # (1) Manual hand stroke detection
        if self.player == "COMPUTER":
            beats_passed = np.where(self.beats_passed)[0]
            if len(beats_passed) > 0:
                last_beat_passed = beats_passed[-1]
                active_pitches = np.where(self.quant_mat[:, last_beat_passed])[0]
                if len(active_pitches) > 0:
                    for pitch_idx in active_pitches:
                        self.play_note(self.heptagon_positions_pitches[pitch_idx], 112)
                        self.quant_mat[pitch_idx, last_beat_passed] = False
                # print('active pitches ' + str(active_pitches))
            # print(beats_passed)
            # self.quant_mat


            # print('qwdnoqwidhqowidh')
            pass
        else:
            if self.detection_method == 'key_tap':
                hand_stroke_detected = self.detect_hand_stroke_using_key_tap_gesture(frame)
            elif self.detection_method == 'manual':
                hand_stroke_detected = self.detect_hand_manual(frame)
            else:
                raise Exception('Non-valid detection method')

            if hand_stroke_detected:
                self.last_event_time = time.time()
                self.reset_after_time

        self.frame_id += 1

    def detect_hand_stroke_using_key_tap_gesture(self, frame):
        """ Method 1: Use leap motion key tap gesture as drum strokes
            Performance: Misses some hits
        """
        # (2) Hand stroke detection using key tap gesture (performance: medium

        hand_stroke_detected = False

        # Get gestures
        for gesture in frame.gestures():

            if gesture.type == Leap.Gesture.TYPE_KEY_TAP:

                keytap = KeyTapGesture(gesture)
                self.play_note_after_detected_hit(keytap.position)

                hand_stroke_detected = True

        return hand_stroke_detected

    def detect_hand_manual(self, frame):
        """ Manual detection of hand stroke motion of both hands
            Performance: much better :) """
        hand_stroke_detected = False
        # check that at least one hand is in the frame
        hands = frame.hands
        if len(hands) > 0:
            for hand in hands:
                _id = hand.id
                position = hand.palm_position

                if self.hand_memory.check_for_hand_stroke(_id, position, self.frame_id):
                    self.play_note_after_detected_hit(position)
                    hand_stroke_detected = True
                # print "id %d, position: %s" % (hand.id, hand.palm_position)
            # print('------')

        return hand_stroke_detected

    def get_pitch_from_position(self, position, heptagon_layout=True):
        if heptagon_layout:

            curr_pos = np.array((position[0], position[2]))

            # nearest neighbor search
            dist = np.sqrt(np.sum(np.square(self.heptagon_positions[:, :2] - curr_pos), axis=1))

            pitch_id = np.argmin(dist)
            pitch = self.heptagon_positions[pitch_id, 2]

            self.user_played_notes.append((time.time() - self.last_bar_start_time, pitch_id))
        else:

            print position
            left, right, front, back = False, False, False, False
            if position[0] < -10:
                left = True
            elif position[0] > -10:
                right = True
            if position[2] < 50: #5:
                back = True
            elif position[2] > 50:#10:
                front = True
            is_low = True
            if position[1] > 150:
                is_low = False

            pitch = None
            if left and front:
                pitch = 36
            elif left and back:
                pitch = 37
            elif right and back:
                pitch = 38
            elif right and front:
                pitch = 39
            if pitch is not None and not is_low:
                pitch += 4

            print "left %d right %d front %d back %d - low %d" % (left, right, front, back, is_low)
        return pitch

    def play_note_after_detected_hit(self, position):
        pitch = self.get_pitch_from_position(position)

        if pitch is not None:
            self.play_note(pitch)
        else:
            print 'Gesture not valid'


    def play_note(self, pitch=None, velocity=112):
        note_on = [0x90, pitch, velocity]  # channel 1, middle C, velocity 112
        self.midi_out.send_message(note_on)


class Player:

    def __init__(self):
        self.scale = ''
        pass

    def change_scale(self, scale):
        self.scale = scale






def main():

    # Create a sample listener and controller
    listener = VirtualHangDrum()
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
