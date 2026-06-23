FROM python:2.7
RUN pip install https://github.com/wibiti/uncompyle2/archive/master.zip
COPY decompile.sh /decompile.sh
RUN chmod +x /decompile.sh
ENTRYPOINT ["/decompile.sh"]
