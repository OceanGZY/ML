import json
import os
import sys
import time
import tensorflow as tf
import seq2seq_model
from get_config import get_config
import io

# 加载配置
gConf = {}
gConf = get_config()
vocab_inp_size = gConf["vocab_inp_size"]
vocab_tar_size = gConf["vocab_tar_size"]
embedding_dim = gConf["embedding_dim"]
units = gConf["layer_size"]
BATCH_SIZE = gConf["batch_size"]

max_length_inp = gConf["max_length"]
max_length_tar = gConf["max_length"]
log_dir = gConf["log_dir"]
writer = tf.summary.create_file_writer(log_dir)


# 对训练语料进行处理，上下文分别加上start end表示
def preprocess_sentence(w):
    w = 'start ' + w + ' end'
    return w


# 定义word2number函数，通过对语料的处理提取词典，并进行word2number处理以及padding补全
def tokenize(vocab_file):
    # 从词典中读取预先生成tokenizer的config，构建词典矩阵
    with open(vocab_file, 'r', encoding="utf-8") as f:
        tokenize_config = json.dumps(json.load(f), ensure_ascii=False)
        lang_tokenizer = tf.keras.preprocessing.text.tokenizer_from_json(tokenize_config)

    # 利用词典进行word2number的转换以及padding处理
    return lang_tokenizer


# 定义数据读取函数，从训练语料中读取数据并进行 word2number处理， 并生成词典
def read_data(path):
    path = os.getcwd() + "/" + path
    if not os.path.exists(path):
        path = os.path.dirname(os.getcwd()) + "/" + path

    lines = io.open(path, encoding="utf-8").read().strip().split("\n")
    word_pairs = [[preprocess_sentence(w) for w in l.split("\t")] for l in lines]
    input_lang, target_lang = zip(*word_pairs)
    input_tokenizer = tokenize(gConf["vocab_inp_path"])
    target_tokenizer = tokenize(gConf["vocab_tar_path"])
    inp_tensor = input_tokenizer.texts_to_sequences(input_lang)
    tar_tensor = target_tokenizer.texts_to_sequences(target_lang)

    inp_tensor = tf.keras.preprocessing.sequence.pad_sequences(inp_tensor, maxlen=max_length_inp, padding='post')
    tar_tensor = tf.keras.preprocessing.sequence.pad_sequences(tar_tensor, maxlen=max_length_tar, padding='post')

    return inp_tensor, input_tokenizer, tar_tensor, target_tokenizer


input_tensor, input_token, target_tensor, target_token = read_data(gConf["seq_data"])
steps_per_epoch = len(input_tensor) // gConf["batch_size"]

BUFFER_SIZE = len(input_tensor)
dataset = tf.data.Dataset.from_tensor_slices((input_tensor, target_tensor)).shuffle(BUFFER_SIZE)
dataset = dataset.batch(BATCH_SIZE, drop_remainder=True)

encode_hidden = seq2seq_model.encoder.initialize_hidden_state()


# 定义训练函数
def train():
    # 从训练语料中读取数据并使用预生成词典word2number的转换
    print("准备数据：%s" % gConf["train_data"])
    print("每个epoch的训练步数：{}".format(steps_per_epoch))

    # 如果有已经有预训练的模型，则加载预训练模型继续训练
    checkpoint_dir = gConf["model_data"]
    try:
        ckpt = tf.io.gfile.listdir(checkpoint_dir)
    except Exception as e:
        print(e)
        ckpt = False
    if ckpt:
        print("重新加载预训练模型")
        seq2seq_model.checkpoint.restore(tf.train.latest_checkpoint(checkpoint_dir))

    # 使用Dataset加载训练数据，Dataset可加速数据的兵法读取并进行训练效率的优化
    checkpoint_prefix = os.path.join(checkpoint_dir, "ckpt")
    start_time = time.time()
    epoch = 0
    train_epoch = gConf["train_epoch"]

    # 开始进行循环训练
    while epoch < train_epoch:
        start_time_epoch = time.time()
        total_loss = 0
        # 进行一个epoch的训练，训练的步数为steps_per_epoch
        for batch, (inp, targ) in enumerate(dataset.take(steps_per_epoch)):
            batch_loss = seq2seq_model.training_step(inp, targ, target_token, encode_hidden)
            total_loss += batch_loss
            print("epoch:{} batch:{} batch_loss:{}".format(epoch, batch, batch_loss))
        # 结束一个epoch的训练后， 更新current_loss， 计算本epoch中每步训练平均耗时、loss值
        step_time_epoch = (time.time() - start_time_epoch) / steps_per_epoch
        step_loss = total_loss / steps_per_epoch
        current_steps = + steps_per_epoch
        epoch_total_time = time.time() - start_time
        print("训练总步数：{} 总耗时：{} epoch平均每步耗时：{} 平均每步loss：{:.4f}".format(current_steps, epoch_total_time, step_time_epoch,
                                                                      step_loss))

        # 将本epoch训练的模型保存，更新模型文件
        seq2seq_model.checkpoint.save(file_prefix=checkpoint_prefix)
        sys.stdout.flush()
        epoch = epoch + 1
        with writer.as_default():
            tf.summary.scalar("loss", step_loss, step=epoch)


# 定义预测函数，根据上下文预测下文对话
def predict(sentence):
    # 从词典中读取预先 生成的tokenizer的config， 构建词典矩阵
    input_tokenizer = tokenize(gConf["vocab_inp_path"])
    target_tokenizer = tokenize(gConf["vocab_tar_path"])

    # 加载预训练模型
    checkpoint_dir = gConf["model_data"]
    seq2seq_model.checkpoint.restore(tf.train.latest_checkpoint(checkpoint_dir))
    # 对输入字句进行处理，加上 start end标示
    sentence = preprocess_sentence(sentence)

    # 进行word2number的转换
    inputs = input_tokenizer.texts_to_sequences(tuple([sentence]))
    # 进行padding补全
    inputs = tf.keras.preprocessing.sequence.pad_sequences(inputs, maxlen=max_length_inp, padding='post')
    inputs = tf.convert_to_tensor(inputs)
    result = ''

    # 初始化一个中间状态
    hidden = [tf.zeros((1, units))]
    # 对输入上文进行encoder编码，提取特征
    encoder_out, encoder_hidden = seq2seq_model.encoder(inputs, hidden)
    decoder_hidden = encoder_hidden
    # decoder的输入从 start的对应id 开始正向输入
    decoder_input = tf.expand_dims([target_tokenizer.word_index['start']], 0)
    # 在最大的语句长度范围内，使用模型中的decoder进行循环解码
    for t in range(max_length_tar):
        # 获得解码结果，并使用argmax确定概率最大的id
        predictions, decoder_hidden, attention_weights = seq2seq_model.decoder(decoder_input, decoder_hidden,
                                                                               encoder_out)
        predicted_id = tf.argmax(predictions[0].numpy())
        # 判断当前id是否为 语句结束表示， 如果是则停止循环解码， 否则进行number2word的转换，并进行语句的拼接
        if target_tokenizer.index_word[predicted_id.numpy()] == 'end':
            break

        result += str(target_tokenizer.index_word[predicted_id.numpy()]) + ' '
        # 将预测得到的id作为下一个时刻的decoder输入
        decoder_input = tf.expand_dims([predicted_id.numpy()], 0)
    return result


# main函数的入口，根据超惨设置的模式启动不同的工作模式
if __name__ == "__main__":
    # 如果启动python时指定了超参文件，则从超参文件中读取超参， 否则从默认的超参文件中读取
    if len(sys.argv) - 1:
        gConf = get_config(sys.argv)
    else:
        gConf = get_config()
    print("\n>> 执行器模式： %s \n" % (gConf["mode"]))
    if gConf["mode"] == "train":
        print("开始进行模型训练")
        train()
    elif gConf["mode"] == "serve":
        print("当前为服务模式，请使用web程序")
