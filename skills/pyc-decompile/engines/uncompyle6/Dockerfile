FROM python:3.8
RUN pip install uncompyle6
COPY decompile.sh /decompile.sh
RUN chmod +x /decompile.sh
ENTRYPOINT ["/decompile.sh"]
