FROM python:3.6.5
MAINTAINER OCEANZY
RUN rm -rf /home/pythonapps/nlp/ugc_apiserver
RUN mkdir -p /home/pythonapps/nlp/ugc_apiserver
RUN pip install --upgrade pip
COPY requirements.txt /home/pythonapps/nlp/ugc_apiserver/
WORKDIR /home/pythonapps/nlp/ugc_apiserver
RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install tensorflow-cpu==2.6.2
COPY . /home/pythonapps/nlp/ugc_apiserver
EXPOSE 5000
CMD ["python","tf_api_service.py"]