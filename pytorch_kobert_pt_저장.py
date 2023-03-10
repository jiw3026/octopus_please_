# -*- coding: utf-8 -*-
"""pytorch_kobert_pt_저장.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1esw7EJj6uoGXufAkjH-YRxklp3dHkgu2

# **Import Module**
"""

import pandas as pd
import numpy as np

import streamlit as st
import streamlit.components.v1 as stc
import joblib
import pandas as pd
import os
import altair as alt

!pip install mxnet
!pip install gluonnlp pandas tqdm
!pip install sentencepiece
!pip install transformers
!pip install torch

!pip install git+https://git@github.com/SKTBrain/KoBERT.git@master

import torch
from torch import nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import gluonnlp as nlp
import numpy as np
from tqdm import tqdm, tqdm_notebook


from kobert.utils import get_tokenizer
from kobert.pytorch_kobert import get_pytorch_kobert_model

from transformers import AdamW
from transformers.optimization import get_cosine_schedule_with_warmup

#GPU 사용
device = torch.device("cuda:0")
#BERT 모델, Vocabulary 불러오기
bertmodel, vocab = get_pytorch_kobert_model()

import os

"""# **Load Data**"""

from google.colab import drive
drive.mount('/content/drive')

data = pd.read_csv(r'/content/drive/MyDrive/kpmg/concat.csv')

data

data.loc[(data['category'] == "중립"), 'category'] = 0
data.loc[(data['category'] == "e"), 'category'] = 1
data.loc[(data['category'] == "s"), 'category'] = 2
data.loc[(data['category'] == "g"), 'category'] = 3

data_list = []
for q, label in zip(data['contents'], data['category'])  :
    data1 = []
    data1.append(q)
    data1.append(str(label))

    data_list.append(data1)

print(data_list[0])
print(data_list[100])
print(data_list[250])
print(data_list[1000])
print(data_list[2500])
print(data_list[3300])

#train & test 데이터로 나누기
from sklearn.model_selection import train_test_split
                                                         
dataset_train, dataset_test = train_test_split(data, test_size=0.25, random_state=0)
print(len(dataset_train))
print(len(dataset_test))

class BERTDataset(Dataset):
    def __init__(self, dataset, sent_idx, label_idx, bert_tokenizer, max_len,
                 pad, pair):
        transform = nlp.data.BERTSentenceTransform(
            bert_tokenizer, max_seq_length=max_len, pad=pad, pair=pair)

        self.sentences = [transform([dataset.iloc[i][sent_idx]]) for i in range(len(dataset))]
        self.labels = [np.int32(dataset.iloc[i][label_idx]) for i in range(len(dataset))]

    def __getitem__(self, i):
        return (self.sentences[i] + (self.labels[i], ))

    def __len__(self):
        return (len(self.labels))

max_len = 64
batch_size = 64
warmup_ratio = 0.1
num_epochs = 10
max_grad_norm = 1
log_interval = 200
learning_rate =  5e-5

tokenizer = get_tokenizer()
tok = nlp.data.BERTSPTokenizer(tokenizer, vocab, lower=False)

data_train = BERTDataset(dataset_train, 0, 1, tok, max_len, True, False)
data_test = BERTDataset(dataset_test, 0, 1, tok, max_len, True, False)

train_dataloader = torch.utils.data.DataLoader(data_train, batch_size=batch_size, num_workers=5, shuffle=True)
test_dataloader = torch.utils.data.DataLoader(data_test, batch_size=batch_size, num_workers=5, shuffle=True)

"""# **KOBERT 학습시키기**"""

class BERTClassifier(nn.Module):
    def __init__(self,
                 bert,
                 hidden_size = 768,
                 num_classes=4,
                 dr_rate=None,
                 params=None):
        super(BERTClassifier, self).__init__()
        self.bert = bert
        self.dr_rate = dr_rate
                 
        self.classifier = nn.Linear(hidden_size , num_classes)
        if dr_rate:
            self.dropout = nn.Dropout(p=dr_rate)
    
    def gen_attention_mask(self, token_ids, valid_length):
        attention_mask = torch.zeros_like(token_ids)
        for i, v in enumerate(valid_length):
            attention_mask[i][:v] = 1
        return attention_mask.float()

    def forward(self, token_ids, valid_length, segment_ids):
        attention_mask = self.gen_attention_mask(token_ids, valid_length)
        
        _, pooler = self.bert(input_ids = token_ids, token_type_ids = segment_ids.long(), attention_mask = attention_mask.float().to(token_ids.device), return_dict=False)

        if self.dr_rate:
            out = self.dropout(pooler)
        return self.classifier(out)

#BERT 모델 불러오기
model = BERTClassifier(bertmodel,  dr_rate=0.5).to(device)

#optimizer와 schedule 설정
no_decay = ['bias', 'LayerNorm.weight']
optimizer_grouped_parameters = [
    {'params': [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': 0.01},
    {'params': [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
]

optimizer = AdamW(optimizer_grouped_parameters, lr=learning_rate)
loss_fn = nn.CrossEntropyLoss()

t_total = len(train_dataloader) * num_epochs
warmup_step = int(t_total * warmup_ratio)

scheduler = get_cosine_schedule_with_warmup(optimizer, num_warmup_steps=warmup_step, num_training_steps=t_total)

def calc_accuracy(X,Y):
    max_vals, max_indices = torch.max(X, 1)
    train_acc = (max_indices == Y).sum().data.cpu().numpy()/max_indices.size()[0]
    return train_acc

"""Train"""

for e in range(num_epochs):
    train_acc = 0.0
    test_acc = 0.0
    model.train()
    for batch_id, (token_ids, valid_length, segment_ids, label) in enumerate(tqdm_notebook(train_dataloader)):
        optimizer.zero_grad()
        token_ids = token_ids.long().to(device)
        segment_ids = segment_ids.long().to(device)
        valid_length= valid_length
        label = label.long().to(device)
        out = model(token_ids, valid_length, segment_ids)
        loss = loss_fn(out, label)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
        optimizer.step()
        scheduler.step()
        train_acc += calc_accuracy(out, label)
    print("epoch {} train acc {}".format(e+1, train_acc / (batch_id+1)))
    model.eval()
    for batch_id, (token_ids, valid_length, segment_ids, label) in enumerate(tqdm_notebook(test_dataloader)):
        token_ids = token_ids.long().to(device)
        segment_ids = segment_ids.long().to(device)
        valid_length= valid_length
        label = label.long().to(device)
        out = model(token_ids, valid_length, segment_ids)
        test_acc += calc_accuracy(out, label)
    print("epoch {} test acc {}".format(e+1, test_acc / (batch_id+1)))

"""TEST"""

def softmax(vals, idx):
    valscpu = vals.cpu().detach().squeeze(0)
    a = 0
    for i in valscpu:
        a += np.exp(i)
    return ((np.exp(valscpu[idx]))/a).item() * 100

def testModel(model, seq):
    cate = ["중립","e","s","g"]
    tmp = [seq]
    transform = nlp.data.BERTSentenceTransform(tok, max_len, pad=True, pair=False)
    tokenized = transform(tmp)

    model.eval()
    result = model(torch.tensor([tokenized[0]]).to(device), [tokenized[1]], torch.tensor(tokenized[2]).to(device))
    idx = result.argmax().cpu().item()
    print("보고서의 카테고리는:", cate[idx])
    print("신뢰도는:", "{:.2f}%".format(softmax(result,idx)))

testModel(model, "이사회 금호석유화학은 지속가능한 기업을 만들기 위해 건전한 지배구조를 구축하고 있습니다. 이사회는 이해관계자의 이익을 대변하고, 경영진에 대한 감독 역할을 하며, 장기적인 관점의 의사결정을 하기 위해 노력합니다.")

testModel(model, "금호석유화학은 시장의 변화에 적절히 대응하고 친환경 포트폴리오 전환을 위해 고부가/친환경 제품 생산, 친환경 자동차 관련 솔루션, 바이오/친환경소재 및 고부가 스페셜티 제품 연구개발 등을 계획 중입니다.")

testModel(model, "당사는 금융상품과 관련하여 신용위험, 유동성위험 및 시장위험에 노출되어 있습니다. 본 주석은 당사가 노출되어 있는 위의 위험에 대한 정보와 당사의 위험관리 목표,정책, 위험 평가 및 관리 절차, 그리고 자본관리에 대해 공시하고 있습니다. 추가적인계량적 정보에 대해서는 본 재무제표 전반에 걸쳐서 공시되어 있습니다.")

testModel(model, "주관하는 ‘2021년 자발적에너지효율목표제 시범사업’ 협약을 통해 에너지 원단위 목표 개선을 위해 노력하고 있으며, 지역사회 및 에너지시민연대에서 주관하는 환경 관련 활동에 참여하며 기후변화 대응 중요성에 대한 공감과 소통을 실천하고 있습니다. ")

testModel(model, "생물다양성 유지")

testModel(model, "생물다양성 유지 및 지속가능성을 추진하는 국제 비영리 환경보호단체")

testModel(model, "아울러 제품 제조, 판매 전단계에 있어서의 탄소배출절감을 위한 공급망 관리 체계를 보다 강화해 나아갈 것입니다.")

testModel(model, "개발에서 유통까지, 원료부터 제품까지, 모든 단계를 아우르는 품질안전의 확보는 필수적입니다.")

testModel(model, "롯데제과는 동반성장아카데미를 온라인으로 연중 운영하며 협력업체의 인적자원 개발을 지원하고 있습니다. ")

testModel(model, "")

print("testModel's state_dict:")
for param_tensor in model.state_dict():
    print(param_tensor, "\w", model.state_dict()[param_tensor].size())

type(model.state_dict())

MODEL_PATH = "saved"
if not os.path.exists(MODEL_PATH):
    os.makedirs(MODEL_PATH)
torch.save(model.state_dict(), os.path.join(MODEL_PATH,"testModel.pt"))

