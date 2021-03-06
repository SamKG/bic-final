import pygame
import os
import subprocess
import math
import random
import timemodule
from neuron import *
from neurongraphics import NeuronG
from neurontopixel import *
import mnist_loader
from dataplotter import DynamicPlot
import numpy as np
import threading
from cython.parallel import prange, parallel
import multiprocessing
from concurrent.futures import *
# Color constant for black
BLACK = (0,0,0)
WHITE = (255,255,255)

def within_bounds(x, x_l, x_r):
	return x >= x_l and x <= x_r

class Label:
	def __init__(self, labels, init_idx=0):
		self.font = pygame.font.SysFont("Segoe UI", 65)
		self.labels = labels
		self.anim_dur = 0
		self.anim_curr = 0
		self.currlabel = self.font.render(self.labels[init_idx], True, WHITE)
		self.alphasurf = pygame.Surface(self.currlabel.get_size(),
										pygame.SRCALPHA)
		self.alphasurf.fill((255,255,255,0))
		self.currlabel.blit(self.alphasurf, (0,0), 
							special_flags=pygame.BLEND_RGBA_MULT)
	
	def update_label(self, idx):
		self.currlabel = self.font.render(self.labels[idx], True, WHITE)
		self.alphasurf = pygame.Surface(self.currlabel.get_size(),
										pygame.SRCALPHA)
	
	def anim_start(self, dur):
		self.anim_dur = dur
		self.anim_curr = 0
		self.alphasurf.fill((255,255,255,255-int(255*self.anim_curr/self.anim_dur)))
		self.currlabel.blit(self.alphasurf, (0,0), 
							special_flags=pygame.BLEND_RGBA_MULT)
	
	def anim_update(self):
		if self.anim_curr < self.anim_dur:
			self.anim_curr += 1
			self.alphasurf.fill((255,255,255,255-int(255*self.anim_curr/self.anim_dur)))
			self.currlabel.blit(self.alphasurf, (0,0), 
								special_flags=pygame.BLEND_RGBA_MULT)
	
	def draw(self, screen, pos):
		screen.blit(self.currlabel, pos)

pygame.init()

# Making the directory for storing frames
frame_dir = "frames"
try:
	os.makedirs(frame_dir)
except FileExistsError:
	filestoremove = [os.path.abspath(os.path.join(frame_dir, f)) 
		for f in os.listdir(frame_dir) 
		if os.path.isfile(os.path.join(frame_dir, f))]
	for f in filestoremove:
		os.remove(f)

curr_recording_idx = 0	
# Making the directory for the video
record_dir = "recordings"
try:
	os.makedirs(record_dir)
except FileExistsError:
	videofiles = [f for f in os.listdir(record_dir)
					if (os.path.isfile(os.path.join(record_dir, f)) and f != ".gitignore")]
	if not (not videofiles):
		vfnums = [int(os.path.splitext(vf)[0]) for vf in videofiles]
		curr_recording_idx = max(vfnums)+1

# Constant for whether to draw neurons
DRAW_NEURONS = True
# Constant for whether to draw labels
DRAW_LABELS = False


# Defines the screen
ssize = 856
size = (ssize,ssize)
screen = pygame.display.set_mode(size)

# Creates the game clock
gclock = pygame.time.Clock()

done = False

# Time stuff for neuron updating
dt = 0.01
timescale = 4
newtimestep = dt*timescale

nclock = timemodule.Clock(dt)

# Getting the MNIST images for the photoreceptive layer
allimages = mnist_loader.get_numpy_array()
imgindex = 0
currimg = allimages[imgindex]

# Defining constants for our neuron grid size and neuron scale and spacing
neurongrid = []
nneurons = 28
neuroncols = nneurons
neuronrows = nneurons
spacing = 29.5
scalefactor = 0.8
scale = 20/(ssize/float(spacing))*scalefactor

# Input grid
inputgrid = PixelGrid(currimg, threshold = None, screen_width = ssize)

# photoreceptive layer
for i in range(0, neuronrows):
	row = []
	for j in range(0, neuroncols):
		row.append(NeuronG(((j+1)*spacing,(i+1)*spacing), scale = scale, is_input = True))
	neurongrid.append(row)

custom_color = lambda val : (val, 255-val, 0)

# Population factor
pop = 10

# Bipolar cells: On center off surround and on center off surround
oncoffs = []
offcons = []
for i in range(0, neuronrows):
	oncoffsrow = []
	offconsrow = []
	for j in range(0, neuroncols):
		newoncoffs = NeuronG(neurongrid[i][j].pos+(5,5), scale = scale, custom_color = custom_color)
		oncoffsrow.append(newoncoffs)
		newoffcons = NeuronG(neurongrid[i][j].pos+(5,5), scale = scale, custom_color = custom_color)
		offconsrow.append(newoffcons)
		# On center
		newoncoffs.add_syn(neurongrid[i][j],
								w_init = 1*pop, tau = 2, sign=1)
		# Off center
		newoffcons.add_syn(neurongrid[i][j],
							w_init = 1*pop, tau = 1, sign=-1)
		
		rotation_1 = 1 + 1j
		rotation_2 = 1
		for _ in range(4):
			curr_i = int(rotation_1.imag) + i
			curr_j = int(rotation_1.real) + j
			if within_bounds(curr_i, 0, neuronrows-1) and within_bounds(curr_j, 0, neuroncols-1):
				# Off surround
				newoncoffs.add_syn(neurongrid[curr_i][curr_j],
									w_init = 0.02*pop, sign=-1)
				# On surround
				newoffcons.add_syn(neurongrid[curr_i][curr_j],
									w_init = 0.02*pop, sign=1)				
			curr_i = int(rotation_2.imag) + i
			curr_j = int(rotation_2.real) + j
			if within_bounds(curr_i, 0, neuronrows-1) and within_bounds(curr_j, 0, neuroncols-1):
				# Off surround
				newoncoffs.add_syn(neurongrid[curr_i][curr_j],
									w_init = 0.1*pop, sign=-1)
				# On surround
				newoffcons.add_syn(neurongrid[curr_i][curr_j],
									w_init = 0.2*pop, sign=1)
				rotation_1 *= 1j
				rotation_2 *= 1j
			
	oncoffs.append(oncoffsrow)
	offcons.append(offconsrow)

# Constant for line detecting ganglion cells
BLOCK_SIZE = 3	

# Line detecting ganglion cells
# each neuron is responsible for detecting its own 3x3 block of on-center off-surround cells surrounding the neuron
line_detectors = []
line_detectors_v = []
line_detectors_h = []
line_detectors_dlr = []
line_detectors_drl = []
for i in range(0,neuronrows):
	row = []
	verts = []
	horzs = []
	diags_lr = [] # top left to bottom right diagonal
	diags_rl = [] # top right to bottom left diagonal
	for j in range(0,neuroncols):
		top_i = i - BLOCK_SIZE//2
		bottom_i = i + BLOCK_SIZE//2
		left_j = j - BLOCK_SIZE//2
		right_j = j + BLOCK_SIZE//2
		pos1 = np.array(oncoffs[i][j].pos)
		pos2 = np.array(oncoffs[top_i][left_j].pos)

		## Initialize neurons (one for every orientation)
		vert = NeuronG(pos = pos1 + (pos2 - pos1)/4,scale = scale,custom_color = custom_color)
		horz = NeuronG(pos = pos1 + (pos2 - pos1)/2,scale = scale,custom_color = custom_color)
		diag_lr = NeuronG(pos = pos1 - (pos2 - pos1)/16,scale = scale,custom_color = custom_color)
		diag_rl = NeuronG(pos = pos1 - (pos2 - pos1)/8,scale = scale,custom_color = custom_color)

		## Add synapses
		# 1) vertical line detector
		for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
			tmp_i = top_i + (d//BLOCK_SIZE)
			tmp_j = left_j + (d%BLOCK_SIZE)
			if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
				if tmp_j == j:
					# we lie on vertical line
					vert.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=0.5*pop) #excite with on
					vert.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.5*pop) #inhibit off
				else:
					vert.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #inhibit when on
					vert.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #excite when off
		
		# 2) Horizontal line detector
		for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
			tmp_i = top_i + (d//BLOCK_SIZE)
			tmp_j = left_j + (d%BLOCK_SIZE)
			if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
				if tmp_i == i:
					# we lie on horizontal line
					horz.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=0.5*pop) #excite with on
					horz.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.5*pop) #inhibit off
				else:
					horz.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #inhibit when on
					horz.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #excite when off
		
		# 3) Diagonal from left to right
		for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
			tmp_i = top_i + (d//BLOCK_SIZE)
			tmp_j = left_j + (d%BLOCK_SIZE)
			if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
				if abs(top_i - tmp_i) == abs(left_j - tmp_j):
					# we lie on l-r diagonal (if distance to topleft corner is same in both x and y)
					diag_lr.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=0.5*pop) #excite with on
					diag_lr.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.5*pop) #inhibit off
				else:
					diag_lr.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #inhibit when on
					diag_lr.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #excite when off

		# 4) Diagonal from right to left
		for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
			tmp_i = top_i + (d//BLOCK_SIZE)
			tmp_j = left_j + (d%BLOCK_SIZE)
			if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
				if abs(bottom_i - tmp_i) == abs(left_j - tmp_j):
					# we lie on l-r diagonal (if distance to topleft corner is same in both x and y)
					diag_rl.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=0.5*pop) #excite with on
					diag_rl.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.5*pop) #inhibit off
				else:
					diag_rl.add_syn(oncoffs[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #inhibit when on
					diag_rl.add_syn(offcons[tmp_i][tmp_j],tau=2,w_init=-0.2*pop) #excite when off

		row.append(vert)
		row.append(horz)
		row.append(diag_lr)
		row.append(diag_rl)
		horzs.append(horz)
		verts.append(vert)
		diags_lr.append(diag_lr)
		diags_rl.append(diag_rl)

	line_detectors.append(row)
	line_detectors_h.append(horzs)
	line_detectors_v.append(verts)
	line_detectors_dlr.append(diags_lr)
	line_detectors_drl.append(diags_rl)

# Mapping back to the photoreceptive layer
output_layer = []
for i in range(0,neuronrows):
	row = []
	for j in range(0,neuroncols):
		outp = NeuronG(neurongrid[i][j].pos+(5,5), scale = scale, custom_color = custom_color)
		row.append(outp)
		outp.add_syn(neurongrid[i][j],tau=1,w_init=1) # compose input layer
	output_layer.append(row)

	
sinusoidchoice = {"horizontal":True, "vertical":True, "diagonal_lr":False, "diagonal_rl":False}

# Horizontal
if sinusoidchoice["horizontal"]:
	for i in range(0,neuronrows):
		row = []
		for j in range(0,neuroncols):
			hneuron = line_detectors_h[i][j]
			top_i = i - BLOCK_SIZE//2
			bottom_i = i + BLOCK_SIZE//2
			left_j = j - BLOCK_SIZE//2
			right_j = j + BLOCK_SIZE//2
			for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
				tmp_i = top_i + (d//BLOCK_SIZE)
				tmp_j = left_j + (d%BLOCK_SIZE)
				if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
					if j%3 == 1 and (d == 3 or d == 1 or d == 5):
						output_layer[tmp_i][tmp_j].add_syn(hneuron,tau=1,w_init=1*pop)
					elif j%3 == 2 and (d == 0 or d == 4 or d == 8):
						output_layer[tmp_i][tmp_j].add_syn(hneuron,tau=1,w_init=1*pop)
					elif j%3 == 0 and (d == 3 or d == 7 or d == 5):
						output_layer[tmp_i][tmp_j].add_syn(hneuron,tau=1,w_init=1*pop)
					else: 
						output_layer[tmp_i][tmp_j].add_syn(hneuron,tau=1,w_init=-0.1*pop)

# Vertical
if sinusoidchoice["vertical"]:
	for i in range(0,neuronrows):
		row = []
		for j in range(0,neuroncols):
			vneuron = line_detectors_v[i][j]
			top_i = i - BLOCK_SIZE//2
			bottom_i = i + BLOCK_SIZE//2
			left_j = j - BLOCK_SIZE//2
			right_j = j + BLOCK_SIZE//2
			for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
				tmp_i = top_i + (d//BLOCK_SIZE)
				tmp_j = left_j + (d%BLOCK_SIZE)
				if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
					if i%3 == 1 and (d == 1 or d == 3 or d == 7):
						output_layer[tmp_i][tmp_j].add_syn(vneuron,tau=1,w_init=0.9*pop)
					elif i%3 == 2 and (d == 0 or d == 4 or d == 8):
						output_layer[tmp_i][tmp_j].add_syn(vneuron,tau=1,w_init=0.9*pop)
					elif i%3 == 3 and (d == 1 or d == 3 or d == 5):
						output_layer[tmp_i][tmp_j].add_syn(vneuron,tau=1,w_init=0.9*pop)
					else: 
						output_layer[tmp_i][tmp_j].add_syn(vneuron,tau=1,w_init=-0.1*pop)					

# LR-Diagonal
if sinusoidchoice["diagonal_lr"]:
	for i in range(0,neuronrows):
		row = []
		for j in range(0,neuroncols):
			dneuron = line_detectors_dlr[i][j]
			top_i = i - BLOCK_SIZE//2
			bottom_i = i + BLOCK_SIZE//2
			left_j = j - BLOCK_SIZE//2
			right_j = j + BLOCK_SIZE//2
			for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
				tmp_i = top_i + (d//BLOCK_SIZE)
				tmp_j = left_j + (d%BLOCK_SIZE)
				if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
					if i == j and i%2 == 1 and (d == 0 or d == 4 or d == 6 or d == 7 or d == 8):
						output_layer[tmp_i][tmp_j].add_syn(dneuron,tau=1,w_init=1*pop)
					elif i == j and i%2 == 0 and (d == 3 or d == 4 or d == 7):
						output_layer[tmp_i][tmp_j].add_syn(dneuron,tau=1,w_init=1*pop)
					else: 
						output_layer[tmp_i][tmp_j].add_syn(dneuron,tau=1,w_init=-0.1*pop)	

# RL-Diagonal
if sinusoidchoice["diagonal_rl"]:
	for i in range(0,neuronrows):
		row = []
		for j in range(0,neuroncols):
			dneuron = line_detectors_drl[i][j]
			top_i = i - BLOCK_SIZE//2
			bottom_i = i + BLOCK_SIZE//2
			left_j = j - BLOCK_SIZE//2
			right_j = j + BLOCK_SIZE//2
			for d in range(0,BLOCK_SIZE*BLOCK_SIZE):
				tmp_i = top_i + (d//BLOCK_SIZE)
				tmp_j = left_j + (d%BLOCK_SIZE)
				if (tmp_i >= 0 and tmp_i < nneurons) and (tmp_j >= 0 and tmp_j < nneurons):
					if j == (nneurons - 1 - i) and i % 2 == 0 and (d == 0 or d == 1 or d == 2 or d == 3 or d == 6):
						output_layer[tmp_i][tmp_j].add_syn(dneuron,tau=1,w_init=1*pop)
					elif j == (nneurons - 1 - i) and i % 2 == 0 and (d == 2 or d == 4 or d == 5):
						output_layer[tmp_i][tmp_j].add_syn(dneuron,tau=1,w_init=1*pop)
					else: 
						output_layer[tmp_i][tmp_j].add_syn(dneuron,tau=1,w_init=-0.1*pop)

# Mapping the modified output layer to pixels
pixelgrid = PixelGrid(output_layer, threshold = 0.75, neuron_to_pixel = True)

def draw_grid_neurons(neurongrid):
	for nrow in neurongrid:
		for neuron in nrow:
			if neuron != None:
				neuron.draw_neuron(screen)

def draw_grid_synapses(neurongrid):
	for nrow in neurongrid:
		for neuron in nrow:
			if neuron != None:
				neuron.draw_synapses(screen)

def update_row_neurons(neuronrow,I_inj = 0):
	for neuron in neuronrow:
		if neuron != None:
			neuron.update(nclock.dt, I_inj = I_inj)


def update_grid_neurons(neurongrid, I_inj = 0):
	executor = ThreadPoolExecutor(max_workers=5)
	res = [ executor.submit(update_row_neurons, row, I_inj) for row in neurongrid]
	res = [future.result() for future in res]

draw_type = 0
record = False
saved_frame = 0
fc = 0
framerate = 20

labeldict = {0:"Pixel Input", 1:"Photoreceptors", 2:"Off-Center-On-Surround", 3:"On-Center-Off-Surround", 4:"Ganglion", 5:"Ganglion Vertical", 6:"Ganglion Horizontal", 7:"Ganglion Diag LR", 8:"Ganglion Diag RL", 9:"Sinusoidal", 10:"Pixel Output"}

mylabel = Label(labeldict, draw_type)
mylabelpos = [size[0]/2-mylabel.currlabel.get_size()[0]/2,50]
labelanimlen = 300
mylabel.update_label(draw_type)
mylabel.anim_start(labelanimlen)

num_layers = 11

while not done:
	pressed = False
	for event in pygame.event.get():
		if event.type == pygame.QUIT:
			done = True
		if event.type == pygame.KEYDOWN:
			if event.key == pygame.K_SPACE:
				draw_type = (draw_type+1)%num_layers
				mylabel.update_label(draw_type)
				mylabel.anim_start(labelanimlen)
				mylabelpos = [size[0]/2-mylabel.currlabel.get_size()[0]/2,50]
			if event.key == pygame.K_BACKSPACE:
				draw_type = (draw_type-1)%num_layers
				mylabel.update_label(draw_type)
				mylabel.anim_start(labelanimlen)
				mylabelpos = [size[0]/2-mylabel.currlabel.get_size()[0]/2,50]
			if event.key == pygame.K_LEFT:
				imgindex = (imgindex-1)%len(allimages)
			if event.key == pygame.K_RIGHT:
				imgindex = (imgindex+1)%len(allimages)
			if event.key == pygame.K_r:
				record = not record
	
	currimg = allimages[imgindex]
				
	
	screen.fill(BLACK)
	
	if DRAW_NEURONS:
		if draw_type == 0:
			inputgrid.update(currimg)
			inputgrid.draw(screen)
			
		if draw_type == 1:
			draw_grid_neurons(neurongrid)
			draw_grid_synapses(neurongrid)
		
		if draw_type == 2:
			draw_grid_synapses(offcons)
			draw_grid_neurons(offcons)
		
		if draw_type == 3:
			draw_grid_synapses(oncoffs)
			draw_grid_neurons(oncoffs)
		
		if draw_type == 4:
			draw_grid_synapses(line_detectors)
			draw_grid_neurons(line_detectors)
		
		if draw_type == 5:
			draw_grid_synapses(line_detectors_v)
			draw_grid_neurons(line_detectors_v)
		
		if draw_type == 6:
			draw_grid_synapses(line_detectors_h)
			draw_grid_neurons(line_detectors_h)
		
		if draw_type == 7:
			draw_grid_synapses(line_detectors_dlr)
			draw_grid_neurons(line_detectors_dlr)
		
		if draw_type == 8:
			draw_grid_synapses(line_detectors_drl)
			draw_grid_neurons(line_detectors_drl)
	
		if draw_type == 9:
			draw_grid_synapses(output_layer)
			draw_grid_neurons(output_layer)
		
		if draw_type == 10:
			pixelgrid.update()
			pixelgrid.draw(screen)
	
	if DRAW_LABELS:
		mylabel.draw(screen, mylabelpos)
		
	this_time = 0
	while this_time < newtimestep:
		this_time += dt
		
		currtime = nclock.get_time()
		
		for i in range(0, neuronrows):
			for j in range(0, neuroncols):
				neurongrid[i][j].update(nclock.dt, I_inj = 10*currimg[i][j])
		update_grid_neurons(oncoffs, I_inj = 0.5)
		update_grid_neurons(offcons, I_inj = 0.5)
		update_grid_neurons(line_detectors)
		update_grid_neurons(output_layer)
		nclock.tick()
		
	fc += 1
	
	mylabel.anim_update()
	
	if record:
		pygame.image.save(screen, 
			os.path.join(frame_dir,('img%d' % saved_frame)+".png"))
		saved_frame += 1
	pygame.display.flip()
	gclock.tick(framerate)

pygame.quit()

frames_exist = not not [f for f in os.listdir(frame_dir) 
			if os.path.isfile(os.path.join(frame_dir, f))]
if frames_exist:
	inputfilestring = frame_dir + '/' + 'img%d.png'
	outputfilestring = record_dir + '/' + str(curr_recording_idx)+'.mp4'
	ffmpegpath = "ffmpeg"
	subprocess.call([ffmpegpath, '-framerate', str(framerate//4), 
	'-i', inputfilestring, '-crf', str(framerate//4), '-pix_fmt', 'yuv420p', 
	outputfilestring])
