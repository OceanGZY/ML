from flask import Flask, request, jsonify
import torch
from tokenizations import tokenization_bert_word_level as tokenization_bert
from tqdm import trange
import torch.nn.functional as F
from transformers import GPT2LMHeadModel, GPT2Config

app = Flask(__name__)


def top_k_top_p_filtering(logits, top_k=0, top_p=0.0, filter_value=-float('Inf')):
    """ Filter a distribution of logits using top-k and/or nucleus (top-p) filtering
        Args:
            logits: logits distribution shape (vocabulary size)
            top_k > 0: keep only top k tokens with highest probability (top-k filtering).
            top_p > 0.0: keep the top tokens with cumulative probability >= top_p (nucleus filtering).
                Nucleus filtering is described in Holtzman et al. (http://arxiv.org/abs/1904.09751)
        From: https://gist.github.com/thomwolf/1a5a29f6962089e871b94cbd09daf317
    """
    assert logits.dim() == 1  # batch size 1 for now - could be updated for more but the code would be less clear
    top_k = min(top_k, logits.size(-1))  # Safety check
    if top_k > 0:
        # Remove all tokens with a probability less than the last token of the top-k
        indices_to_remove = logits < torch.topk(logits, top_k)[0][..., -1, None]
        logits[indices_to_remove] = filter_value

    if top_p > 0.0:
        sorted_logits, sorted_indices = torch.sort(logits, descending=True)
        cumulative_probs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)

        # Remove tokens with cumulative probability above the threshold
        sorted_indices_to_remove = cumulative_probs > top_p
        # Shift the indices to the right to keep also the first token above the threshold
        sorted_indices_to_remove[..., 1:] = sorted_indices_to_remove[..., :-1].clone()
        sorted_indices_to_remove[..., 0] = 0

        indices_to_remove = sorted_indices[sorted_indices_to_remove]
        logits[indices_to_remove] = filter_value
    return logits


def sample_sequence(model, context, length, n_ctx, tokenizer, temperature=1.0, top_k=30, top_p=0.0,
                    repitition_penalty=1.0,
                    device='cpu'):
    context = torch.tensor(context, dtype=torch.long, device=device)
    context = context.unsqueeze(0)
    generated = context
    with torch.no_grad():
        for _ in trange(length):
            inputs = {'input_ids': generated[0][-(n_ctx - 1):].unsqueeze(0)}
            outputs = model(
                **inputs)  # Note: we could also use 'past' with GPT-2/Transfo-XL/XLNet (cached hidden-states)
            next_token_logits = outputs[0][0, -1, :]
            for id in set(generated):
                next_token_logits[id] /= repitition_penalty
            next_token_logits = next_token_logits / temperature
            next_token_logits[tokenizer.convert_tokens_to_ids('[UNK]')] = -float('Inf')
            filtered_logits = top_k_top_p_filtering(next_token_logits, top_k=top_k, top_p=top_p)
            next_token = torch.multinomial(F.softmax(filtered_logits, dim=-1), num_samples=1)
            generated = torch.cat((generated, next_token.unsqueeze(0)), dim=1)
    return generated.tolist()[0]


def generate(n_ctx, model, context, length, tokenizer, temperature=1, top_k=0, top_p=0.0, repitition_penalty=1.0,
             device='cpu'):
    return sample_sequence(model, context, length, n_ctx, tokenizer=tokenizer, temperature=temperature, top_k=top_k,
                           top_p=top_p,
                           repitition_penalty=repitition_penalty, device=device)


def text_generator(text, length):
    device = "cpu"
    tokenizer = tokenization_bert.BertTokenizer(vocab_file="pre_poetry_model/vocab.txt")
    model = GPT2LMHeadModel.from_pretrained("pre_poetry_model/")
    model.to(device)
    model.eval()
    context_tokens = tokenizer.convert_tokens_to_ids(tokenizer.tokenize(text))
    poems = []
    for i in range(5):
        out = generate(n_ctx=model.config.n_ctx,
                       model=model,
                       context=context_tokens,
                       length=length,
                       tokenizer=tokenizer,
                       temperature=1,
                       top_k=8,
                       top_p=0,
                       repitition_penalty=1.0,
                       device=device)
        gtext = tokenizer.convert_ids_to_tokens(out)
        for i, item in enumerate(gtext):
            if item == '[MASK]':
                gtext[i] = ''
            elif item == '[CLS]':
                gtext[i] = ''
            elif item == '[SEP]':
                gtext[i] = ''
        poem = ''.join(gtext).replace('##', '').strip()
        poems.append(poem)
    return poems


@app.route("/api/v0.1/poetry", methods=['GET', 'POST'])
def poetry_create():
    text = request.args.get('text')
    length = 32
    res_text = text_generator(text, length)
    poems = {}
    for index, item in enumerate(res_text):
        if len(item) > 32:
            item = item[0:31]
        poems["poem_%s" % index] = item
    res = {
        'res_poetry': poems
    }
    return jsonify(res)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5002)
