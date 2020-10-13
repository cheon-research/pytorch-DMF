"""
Implementation for "Joint Neural Collaborative Filtering for Recommender Systems"
ACM Transactions on Information Systems, Vol. 37, No. 4, Article 39. (August 2019)

https://dl.acm.org/doi/10.1145/3343117
https://arxiv.org/pdf/1907.03459.pdf

by Sangjin Cheon (cheon.research @ gmail.com)
University of Seoul, Korea
"""

import torch
import torch.optim as optim
import numpy as np

import time

from model import DMF
import dataset
from functions import *


def run(data, num_ng, gpu='0'):
	import os
	os.environ['CUDA_VISIBLE_DEVICES'] = gpu
	print("##### {} Negative Samples experiment on {} dataset".format(num_ng, data))
	
	learning_rate = 0.0001
	batch_size = 256
	epochs = 100
	num_ng = num_ng

	if torch.cuda.is_available():
		device = torch.device('cuda')
		torch.cuda.manual_seed_all(706)
		FloatTensor = torch.cuda.FloatTensor
	else:
		device = torch.device('cpu')
		torch.manual_seed(706)
		FloatTensor = torch.FloatTensor

	# Datasets
	user_matrix, item_matrix, train_u, train_i, train_r, neg_candidates, u_cnt, user_rating_max = dataset.load_train_data(data)
	if data == 'ml-1m':
		eval_batch_size = 100 * 151
		test_users, test_items = dataset.load_test_ml_1m()
	elif data == 'ml-100k':
		eval_batch_size = 100 * 41
		test_users, test_items = dataset.load_test_ml_100k()
	elif dataset == 'yelp':
		eval_batch_size = 100 * 81  # yelp 25677 = 81 * 317
		test_users, test_items = dataset.load_test_yelp()
	n_users, n_items = user_matrix.shape[0], user_matrix.shape[1]

	user_array = user_matrix.toarray()
	item_array = item_matrix.toarray()
	user_idxlist, item_idxlist = list(range(n_users)), list(range(n_items))

	# Model
	model = DMF(n_users, n_items).to(device)
	loss_function = torch.nn.BCELoss()
	optimizer = optim.Adam(model.parameters(), lr=learning_rate)

	best_hr = 0.0
	for epoch in range(epochs):
		# Train
		model.train()  # Enable dropout (if have).

		# Negative Sampling
		new_users, new_items, new_labels = dmf_negative_sampling(train_u, train_i, train_r, u_cnt, neg_candidates, num_ng)

		idxlist = np.array(range(len(new_users)))
		np.random.shuffle(idxlist)
		epoch_loss = .0

		start_time = time.time()
		for batch_idx, start_idx in enumerate(range(0, len(idxlist), batch_size)):
			end_idx = min(start_idx + batch_size, len(idxlist))
			idx = idxlist[start_idx:end_idx]

			u_ids = new_users.take(idx)
			i_ids = new_items.take(idx)
			
			users = FloatTensor(user_array.take(u_ids, axis=0))
			items = FloatTensor(item_array.take(i_ids, axis=0))
			labels = FloatTensor(new_labels.take(idx))

			rating_max = FloatTensor(user_rating_max.take(u_ids, axis=0))
			Y_ui = labels / rating_max  # for Normalized BCE

			optimizer.zero_grad()

			preds = model(users, items)
			loss = loss_function(preds, Y_ui)

			epoch_loss += loss.item()
			loss.backward()
			optimizer.step()
		train_time = time.time() - start_time

		# Evaluate
		model.eval()
		HR, NDCG = [], []

		time_E = time.time()
		for start_idx in range(0, len(test_users), eval_batch_size):
			end_idx = min(start_idx + eval_batch_size, len(test_users))
			u_ids = test_users[start_idx:end_idx]
			i_ids = test_items[start_idx:end_idx]

			users = FloatTensor(user_array.take(u_ids, axis=0))
			items = FloatTensor(item_array.take(i_ids, axis=0))

			preds = model(users, items).detach().cpu()

			e_batch_size = eval_batch_size // 100  # faster eval
			preds = torch.chunk(preds, e_batch_size)
			chunked_items = torch.chunk(torch.IntTensor(i_ids), e_batch_size)

			for i, pred in enumerate(preds):
				_, indices = torch.topk(pred, 10)
				recommends = torch.take(chunked_items[i], indices).numpy().tolist()

				gt_item = chunked_items[i][0].item()
				HR.append(hit(gt_item, recommends))
				NDCG.append(ndcg(gt_item, recommends))

		eval_time = time.time() - time_E
		#if epoch % 10 == 0:
		print('[Epoch {:03d}] Loss: {:.6f}'.format(epoch, epoch_loss / (batch_idx + 1)) + '\ttrain: ' + time.strftime('%M: %S', time.gmtime(train_time)) + '\tHR: {:.4f}\tNDCG: {:.4f}'.format(np.mean(HR), np.mean(NDCG)))

		if np.mean(HR) > best_hr:
			best_hr, best_ndcg, best_epoch = np.mean(HR), np.mean(NDCG), epoch

	print('End. Best epoch {:02d}: HR = {:.4f}, NDCG = {:.4f}'.format(best_epoch, best_hr, best_ndcg))