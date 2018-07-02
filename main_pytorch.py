import numpy as np 
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset
from torch.autograd import Variable


def MNISTdataLoader(path):
    ##load moving mnist data, data shape = [time steps, batch size, width, height] = [20, batch_size, 64, 64]
    data = np.load(path)
    train = data[:, 0:7000, :, :]
    test = data[:, 7000:10000, :, :]
    return train, test

class MovingMNISTdataset(Dataset):
    ##dataset class for moving MNIST data
    def __init__(self, path):
        self.path = path
        self.train, self.test = MNISTdataLoader(path)

    def __len__(self):
        return len(self.train[0])

    def __getitem__(self, indx, mode = "train"):
        ##getitem method
        if mode == "train":
            self.trainsample_ = self.train[:, 10*indx:10*(indx+1), :, :]
            self.sample_ = self.trainsample_

        if mode == "test":
            self.testsample_ = self.test[:, 10*indx:10*(index+1), :, :]
            self.sample_ = self.trainsample_

        self.sample = torch.from_numpy(np.expand_dims(self.sample_, axis = 2)).float()
        return self.sample

def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        m.weight.data.normal_(0.0, 0.02)
    elif classname.find('BatchNorm') != -1:
        m.weight.data.normal_(1.0, 0.02)
        m.bias.data.fill_(0)

class CLSTM_cell(nn.Module):
    """ConvLSTMCell
    """
    def __init__(self, shape, input_channels, filter_size, num_features):
        super(CLSTM_cell, self).__init__()

        self.shape = shape ##H, W
        self.input_channels = input_channels
        self.filter_size = filter_size
        self.num_features = num_features
        self.padding = (filter_size - 1)/2
        self.conv = nn.Conv2d(self.input_channels + self.num_features, 4*self.num_features, self.filter_size, 1, self.padding)

    def forward(self, input, hidden_state):
        hx, cx = hidden_state
        combined = torch.cat((input, hx), 1)
        gates = self.conv(combined)

        ingate, forgetgate, cellgate, outgate = torch.split(gates, self.num_features, dim=1)
        ingate = F.sigmoid(ingate)
        forgetgate = F.sigmoid(forgetgate)
        cellgate = F.tanh(cellgate)
        outgate = F.sigmoid(outgate)

        cy = (forgetgate*cx) + (ingate*cellgate)
        hy = outgate * F.tanh(cy)

        return hy, cy

    def init_hidden(self, batch_size):
        return (Variable(torch.zeros(batch_size, self.num_features, self.shape[0], self.shape[1])).cuda(), 
                Variable(torch.zeros(batch_size, self.num_features, self.shape[0], self.shape[1])).cuda())

class CLSTM(nn.Module):
    """Initialize a basic Conv LSTM cell.
    Args:
      shape: int tuple thats the height and width of the hidden states h and c()
      filter_size: int that is the height and width of the filters
      num_features: int thats the num of channels of the states, like hidden_size
      
    """
    def __init__(self, shape, input_chans, filter_size, num_features,num_layers):
        super(CLSTM, self).__init__()
        
        self.shape = shape#H,W
        self.input_chans=input_chans
        self.filter_size=filter_size
        self.num_features = num_features
        self.num_layers=num_layers
        cell_list=[]
        cell_list.append(CLSTM_cell(self.shape, self.input_chans, self.filter_size, self.num_features).cuda())#the first
        #one has a different number of input channels
        
        for idcell in xrange(1,self.num_layers):
            cell_list.append(CLSTM_cell(self.shape, self.num_features, self.filter_size, self.num_features).cuda())
        self.cell_list=nn.ModuleList(cell_list)      

    
    def forward(self, input, hidden_state):
        """
        args:
            hidden_state:list of tuples, one for every layer, each tuple should be hidden_layer_i,c_layer_i
            input is the tensor of shape seq_len,Batch,Chans,H,W
        """

        #current_input = input.transpose(0, 1)#now is seq_len,B,C,H,W
        current_input=input
        next_hidden=[]#hidden states(h and c)
        seq_len=current_input.size(0)

        
        for idlayer in xrange(self.num_layers):#loop for every layer

            hidden_c=hidden_state[idlayer]#hidden and c are images with several channels
            all_output = []
            output_inner = []            
            for t in xrange(seq_len):#loop for every step
                hidden_c=self.cell_list[idlayer](current_input[t, :, :, :, :],hidden_c)#cell_list is a list with different conv_lstms 1 for every layer

                output_inner.append(hidden_c[0])

            next_hidden.append(hidden_c)
            current_input = torch.cat(output_inner, 0).view(current_input.size(0), *output_inner[0].size())#seq_len,B,chans,H,W


        return next_hidden, current_input

    def init_hidden(self,batch_size):
        init_states=[]#this is a list of tuples
        for i in xrange(self.num_layers):
            init_states.append(self.cell_list[i].init_hidden(batch_size))
        return init_states

class MNISTDecoder(nn.Module):
    """
    Decoder for MNIST
    """
    def __init__(self, shape, input_channels, filter_size, num_features):
        super(MNISTDecoder, self).__init__()

        self.shape = shape ##H, W
        self.input_channels = input_channels
        self.filter_size = filter_size
        self.num_features = num_features
        self.padding = (filter_size - 1)/2
        self.conv = nn.Conv2d(self.input_channels, self.num_features, self.filter_size, 1, self.padding)

    def forward(self, state_input_layer1, state_input_layer2):
        """
        Convlutional Decoder for ConvLSTM RNN, forward pass
        """
        inputlayer = torch.cat((state_input_layer1, state_input_layer2),1)
        output = self.conv(inputlayer)

        return output 



###########Usage#######################################    
mnistdata = MovingMNISTdataset("mnist_test_seq.npy")
getitem = mnistdata.__getitem__(10, mode = "train")#shape of 20 10 1 64 64, seq, batch, inpchan, shape

num_features=10
filter_size=5
batch_size=10
shape=(64,64)#H,W
inp_chans=1
nlayers=2
seq_len=10

input = getitem.cuda()
#input = Variable(torch.rand(batch_size,seq_len,inp_chans,shape[0],shape[1])).cuda()

conv_lstm=CLSTM(shape, inp_chans, filter_size, num_features,nlayers)
conv_lstm.apply(weights_init)
conv_lstm.cuda()

decoder = MNISTDecoder(shape, 20, 3, 1)
decoder.apply(weights_init)
decoder.cuda()

# print 'convlstm module:',conv_lstm

# print 'params:'
# params=conv_lstm.parameters()
# for p in params:
#    print 'param ',p.size()
#    print 'mean ',torch.mean(p)


hidden_state=conv_lstm.init_hidden(batch_size)
# print 'hidden_h shape ',len(hidden_state)
# print 'hidden_h shape ',hidden_state[0][0].size()
out=conv_lstm(input,hidden_state)
# print 'out shape',out[1].size()
# print 'len hidden ', len(out[0])
# print 'next hidden',out[0][0][0].size()
# print 'convlstm dict',conv_lstm.state_dict().keys()
pred = decoder(out[0][0][0], out[0][0][1])

print 'pred', pred.shape


L=torch.sum(out[1])
L.backward()
