FROM python:3.8
RUN pip install decompyle3
COPY decompile.sh /decompile.sh
RUN chmod +x /decompile.sh
ENTRYPOINT ["/decompile.sh"]
