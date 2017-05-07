import os
import model
import numpy as np
import tensorflow as tf
import random
import time
from gen_dataloader import Gen_Data_loader
from dis_dataloader import Dis_dataloader
from text_classifier import TextCNN
from rollout import ROLLOUT
from target_lstm import TARGET_LSTM
import io_utils
import cPickle

#########################################################################################
#  Generator  Hyper-parameters
#########################################################################################
EMB_DIM = 32
HIDDEN_DIM = 32
START_TOKEN = 0

PRE_EPOCH_NUM =  240
TRAIN_ITER = 1  # generator
SEED = 88
BATCH_SIZE = 64

D_WEIGHT = 1

D = max(int(5 * D_WEIGHT), 1)
##########################################################################################

TOTAL_BATCH = 800

#########################################################################################
#  Discriminator  Hyper-parameters
#########################################################################################
dis_embedding_dim = 64
dis_filter_sizes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20]
dis_num_filters = [100, 200, 200, 200, 200, 100, 100, 100, 100, 100, 160, 160]
dis_dropout_keep_prob = 0.75
dis_l2_reg_lambda = 0.2

# Training parameters
dis_batch_size = 64
dis_num_epochs = 3
dis_alter_epoch = 50


##############################################################################################

DATA_DIR = "../../data"

#sequences = io_utils.read_sentences_csv(os.path.join(DATA_DIR, 'deaths-in-india-satp-dfe.csv'))
#sequences = [sequence for sequence in sequences if len(sequence) < 70]
#smiles = io_utils.read_smiles_smi(os.path.join(DATA_DIR, '250k.smi'))
sequences = io_utils.read_songs_txt(os.path.join(DATA_DIR, 'jigs.txt'))

sequences = [seq for seq in sequences if len(seq) < 100]
print "Average equence length:"
print (np.average([len(seq) for seq in sequences]))

def pct(a, b):
    if len(b) == 0:
        return 0
    return float(len(a)) / len(b)


def build_vocab(sequences, pad_char = '_', start_char = '^'):
    i = 1
    char_dict, ord_dict = {start_char: 0}, {0: start_char}
    for sequence in sequences:
        for c in sequence:
            if c not in char_dict:
                char_dict[c] = i
                ord_dict[i] = c
                i += 1
    char_dict[pad_char], ord_dict[i] = i, pad_char
    return char_dict, ord_dict

char_dict, ord_dict = build_vocab(sequences)

def pad(sequence, n, pad_char = '_'):
    if n < len(sequence):
        return sequence
    return sequence + [pad_char] * (n - len(sequence))

def unpad(sequence, pad_char = '_'):
    def reverse(s): return s[::-1]
    rev = reverse(sequence)
    for i, elem in enumerate(rev):
        if elem != pad_char:
            return reverse(rev[i:])
    return sequence

def encode_smile(sequence, max_len): return [char_dict[c] for c in pad(sequence, max_len)]
def decode_smile(ords): return ' '.join(unpad([ord_dict[o] for o in ords]))

NUM_EMB = len(char_dict) + 1

def verify_sequence(decoded):
    return True



notes = ['C,', 'D,', 'E,', 'F,', 'G,', 'A,', 'B,', 'C', 'D', 'E', 'F', 'G', 'A', 'B',
    'c', 'd', 'e', 'f', 'g', 'a', 'b', 'c\'', 'd\'', 'e\'', 'f\'', 'g\'', 'a\'', 'b\'']

notes_and_frequencies = {'C,' : 65.41, 'D,' : 73.42, 'E,' : 82.41, 'F,' : 87.31, 'G,' : 98, 'A,' : 110, 'B,' : 123.47, 
    'C' : 130.81, 'D' : 146.83, 'E' : 164.81, 'F' : 174.61, 'G' : 196, 'A' : 220, 'B' : 246.94,
    'c' : 261.63, 'd' : 293.66, 'e' : 329.63, 'f' : 349.23, 'g' : 392, 'a' : 440, 'b' : 493.88,
    'c\'' : 523.25, 'd\'' : 587.33, 'e\'' : 659.25, 'f\'' : 698.46, 'g\'' : 783.99, 'a\'' : 880, 'b\'' : 987.77}

def is_note(note): return note in notes

def is_valid_sequence(sequence):
    clean_sequence = clean(sequence)
    return np.sum([(1 if is_note(note) else 0) for note in clean_sequence]) > 1 if len(sequence) != 0 else False

def clean(sequence): 
    return [note.strip("_^=\\0123456789") for note in sequence if is_note(note.strip("_^=\\0123456789"))]

def notes_and_successors(sequence): return [(note, sequence[i+1]) for i, note in enumerate(sequence) if i < len(sequence) - 1]

def is_perf_fifth(note, succ): 
        ratio = notes_and_frequencies[succ] / notes_and_frequencies[note]
        return ratio < 1.55 and ratio > 1.45



def tonality(sequence):
    clean_sequence = clean(sequence)

    notes_and_succs = notes_and_successors(clean_sequence)

    return np.mean([(1 if is_perf_fifth(note, successor) else 0) for note, successor in notes_and_succs]) if len(sequence) > 1 else 0



# Order of dissonance (best to worst): P5, P4, M6, M3, m3, m6, M2, m7, m2, M7, TT
# To be melodic, it must be a M6 or better
def melodicity(sequence):
    clean_sequence = clean(sequence)

    notes_and_succs = notes_and_successors(clean_sequence)

    def is_perf_fourth(note, succ):
        ratio = notes_and_frequencies[succ] / notes_and_frequencies[note]
        return ratio < 1.38 and ratio > 1.28

    def is_major_sixth(note, succ):
        ratio = notes_and_frequencies[succ] / notes_and_frequencies[note]
        return ratio < 1.72 and ratio > 1.62

    def is_harmonic(note, succ): 
        ratio = notes_and_frequencies[succ] / notes_and_frequencies[note]
        return is_perf_fifth(note, succ) or is_perf_fourth(note, succ) or is_major_sixth(note, succ)

    return np.mean([(1 if is_harmonic(note, successor) else 0) for note, successor in notes_and_succs]) if len(sequence) > 1 else 0



def ratio_of_steps(sequence):
    clean_sequence = clean(sequence)

    notes_and_succs = notes_and_successors(clean_sequence)

    def is_step(note, succ): return abs(notes.index(note) - notes.index(succ)) == 1

    return np.mean([(1 if is_step(note, successor) else 0) for note, successor in notes_and_succs]) if len(sequence) > 1 else 0



def reward(decoded):
    if is_valid_sequence(decoded):
        return melodicity(decoded)
    else:
        return 0

def make_reward(train_smiles):
    def batch_reward(samples):
        decoded = [decode_smile(sample) for sample in samples]
        pct_unique = float(len(list(set(decoded)))) / len(decoded)

        def count(x, xs):
            ret = 0
            for y in xs:
                if y == x:
                    ret += 1
            return ret

        return np.array([reward(sample) / count(sample, decoded) for sample in decoded])
    return batch_reward

def objective(samples):
    return np.mean([reward(sample) for sample in samples])
    
    #count_unique = [len(set(sample)) for sample in samples]
    #return pct(verified, samples) * (1 - pct(in_train, verified)) * (np.mean(count_unique) / float(max_len))

def print_molecules(model_samples, train_smiles):
    samples = [decode_smile(s) for s in model_samples]
    unique_samples = list(set(samples))
    print 'Unique samples. Pct: {}'.format(pct(unique_samples, samples))
    verified_samples = filter(verify_sequence, samples)

    for s in samples[0:10]:
        print s
    print 'Verified samples. Pct: {}'.format(pct(verified_samples, samples))
    for s in verified_samples[0:10]:
        print s
    print 'Objective: {}'.format(objective(samples))
    print "Average sample length"
    print (np.average([len(unpad(seq)) for seq in model_samples]))

SEQ_LENGTH = max(map(len, sequences))

positive_samples = [encode_smile(smile, SEQ_LENGTH) for smile in sequences if verify_sequence(smile)]
generated_num = len(positive_samples)

print('Starting SeqGAN with {} positive samples'.format(generated_num))
print('Size of alphabet is {}'.format(NUM_EMB))
print('Sequence length is {}'.format(SEQ_LENGTH))


##############################################################################################

class Generator(model.LSTM):
    def g_optimizer(self, *args, **kwargs):
        return tf.train.AdamOptimizer(0.002)  # ignore learning rate


def generate_samples(sess, trainable_model, batch_size, generated_num):
    #  Generated Samples
    generated_samples = []
    start = time.time()
    for _ in range(int(generated_num / batch_size)):
        generated_samples.extend(trainable_model.generate(sess))
    end = time.time()
    #print 'Sample generation time:', (end - start)
    return generated_samples


def target_loss(sess, target_lstm, data_loader):
    supervised_g_losses = []
    data_loader.reset_pointer()

    for it in xrange(data_loader.num_batch):
        batch = data_loader.next_batch()
        g_loss = sess.run(target_lstm.pretrain_loss, {target_lstm.x: batch})
        supervised_g_losses.append(g_loss)

    return np.mean(supervised_g_losses)



def pre_train_epoch(sess, trainable_model, data_loader):
    supervised_g_losses = []
    data_loader.reset_pointer()

    for it in xrange(data_loader.num_batch):
        batch = data_loader.next_batch()
        _, g_loss, g_pred = trainable_model.pretrain_step(sess, batch)
        supervised_g_losses.append(g_loss)

    return np.mean(supervised_g_losses)



# This is a hack. I don't even use LIkelihood data loader tbh
likelihood_data_loader = Gen_Data_loader(BATCH_SIZE)

def pretrain(sess, generator, target_lstm, train_discriminator):
    #samples = generate_samples(sess, target_lstm, BATCH_SIZE, generated_num)
    gen_data_loader = Gen_Data_loader(BATCH_SIZE)
    gen_data_loader.create_batches(positive_samples)

    #  pre-train generator
    print 'Start pre-training...'
    for epoch in xrange(PRE_EPOCH_NUM):
        print 'pre-train epoch:', epoch
        loss = pre_train_epoch(sess, generator, gen_data_loader)
        if epoch % 5 == 0:
            samples = generate_samples(sess, generator, BATCH_SIZE, generated_num)
            likelihood_data_loader.create_batches(samples)
            test_loss = target_loss(sess, target_lstm, likelihood_data_loader)
            print 'pre-train epoch ', epoch, 'test_loss ', test_loss, 'train_loss ', loss

            print_molecules(samples, sequences)


    samples = generate_samples(sess, generator, BATCH_SIZE, generated_num)
    likelihood_data_loader.create_batches(samples)
    test_loss = target_loss(sess, target_lstm, likelihood_data_loader)

    samples = generate_samples(sess, generator, BATCH_SIZE, generated_num)
    likelihood_data_loader.create_batches(samples)

    print 'Start training discriminator...'
    for i in range(dis_alter_epoch):
        print 'epoch {}'.format(i)
        train_discriminator()

def main():
    random.seed(SEED)
    np.random.seed(SEED)

    #assert START_TOKEN == 0

    vocab_size = NUM_EMB
    dis_data_loader = Dis_dataloader()

    best_score = 1000
    generator = Generator(vocab_size, BATCH_SIZE, EMB_DIM, HIDDEN_DIM, SEQ_LENGTH, START_TOKEN)
    target_lstm = TARGET_LSTM(vocab_size, BATCH_SIZE, EMB_DIM, HIDDEN_DIM, SEQ_LENGTH, 0)

    with tf.variable_scope('discriminator'):
        cnn = TextCNN(
            sequence_length=SEQ_LENGTH,
            num_classes=2,
            vocab_size=vocab_size,
            embedding_size=dis_embedding_dim,
            filter_sizes=dis_filter_sizes,
            num_filters=dis_num_filters,
            l2_reg_lambda=dis_l2_reg_lambda)

    cnn_params = [param for param in tf.trainable_variables() if 'discriminator' in param.name]
    # Define Discriminator Training procedure
    dis_global_step = tf.Variable(0, name="global_step", trainable=False)
    dis_optimizer = tf.train.AdamOptimizer(1e-4)
    dis_grads_and_vars = dis_optimizer.compute_gradients(cnn.loss, cnn_params, aggregation_method=2)
    dis_train_op = dis_optimizer.apply_gradients(dis_grads_and_vars, global_step=dis_global_step)

    config = tf.ConfigProto()
    # config.gpu_options.per_process_gpu_memory_fraction = 0.5
    config.gpu_options.allow_growth = True
    sess = tf.Session(config=config)

    def train_discriminator():
        if D_WEIGHT == 0:
            return

        negative_samples = generate_samples(sess, generator, BATCH_SIZE, generated_num)

        #  train discriminator
        dis_x_train, dis_y_train = dis_data_loader.load_train_data(positive_samples, negative_samples)
        dis_batches = dis_data_loader.batch_iter(
            zip(dis_x_train, dis_y_train), dis_batch_size, dis_num_epochs
        )

        for batch in dis_batches:
            x_batch, y_batch = zip(*batch)
            feed = {
                cnn.input_x: x_batch,
                cnn.input_y: y_batch,
                cnn.dropout_keep_prob: dis_dropout_keep_prob
            }
            _, step, loss, accuracy = sess.run([dis_train_op, dis_global_step, cnn.loss, cnn.accuracy], feed)
        print 'Discriminator loss: {} Accuracy: {}'.format(loss, accuracy)


    # Pretrain is checkpointed and only execcutes if we don't find a checkpoint
    saver = tf.train.Saver()
    pretrain_ckpt_file = 'checkpoints/pretrain_ckpt'
    if os.path.isfile(pretrain_ckpt_file + '.meta'):
        saver.restore(sess, pretrain_ckpt_file)
        print 'Pretrain loaded from previous checkpoint {}'.format(pretrain_ckpt_file)
    else:
        sess.run(tf.global_variables_initializer())
        pretrain(sess, generator, target_lstm, train_discriminator)
        path = saver.save(sess, pretrain_ckpt_file)
        print 'Pretrain finished and saved at {}'.format(path)

    rollout = ROLLOUT(generator, 0.8)

    print '#########################################################################'
    print 'Start Reinforcement Training Generator...'

    for total_batch in range(TOTAL_BATCH):
        print '#########################################################################'
        print 'Training generator with Reinforcement Learning. Epoch {}'.format(total_batch)
        for it in range(TRAIN_ITER):
            samples = generator.generate(sess)
            rewards = rollout.get_reward(sess, samples, 16, cnn, make_reward(sequences), D_WEIGHT)
            print(rewards)
            g_loss = generator.generator_step(sess, samples, rewards)

            print 'total_batch: ', total_batch, 'g_loss: ', g_loss

        if total_batch % 1 == 0 or total_batch == TOTAL_BATCH - 1:
            samples = generate_samples(sess, generator, BATCH_SIZE, generated_num)
            likelihood_data_loader.create_batches(samples)
            test_loss = target_loss(sess, target_lstm, likelihood_data_loader)
            print 'total_batch: ', total_batch, 'test_loss: ', test_loss

            print_molecules(samples, sequences)

            if test_loss < best_score:
                best_score = test_loss
                print 'best score: ', test_loss

        rollout.update_params()

        # generate for discriminator
        print 'Start training discriminator'
        for i in range(D):
            print 'epoch {}'.format(i)
            train_discriminator()



if __name__ == '__main__':
    main()
