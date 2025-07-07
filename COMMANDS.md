source venv/bin/activate && source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF && python -m src.arbitrage_commands.simple_bot \
       --amount 0.01 \
       --interval 120 \
       --tolerance 0.2

source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF && python -m src.arbitrage_commands.complex_bot 0.1 120


source futarchy_env/bin/activate && source venv/bin/activate && source .env.0xDA36a35CA4Fe6214C37a452159C0C9EAd45D5919 && python -m src.arbitrage_commands.simple_bot \
       --amount 0.01 \
       --interval 120 \
       --tolerance 0.2

source futarchy_env/bin/activate && source .env.0xDA36a35CA4Fe6214C37a452159C0C9EAd45D5919 && python -m src.arbitrage_commands.complex_bot 0.1 120