#!/bin/bash
# Vercel build script: 确保 knowledge submodule 被正确拉取
# 如果 submodule 为空（Vercel 未能自动拉取），则手动 clone

if [ ! -f "knowledge/pool/demand_pool.json" ]; then
    echo "Submodule not populated, cloning knowledge base..."
    rm -rf knowledge
    git clone https://${GITHUB_TOKEN}@github.com/Serenasnchen/presale-knowledge-base.git knowledge
    echo "Knowledge base cloned successfully"
else
    echo "Knowledge submodule already populated"
fi

echo "Knowledge files: $(find knowledge -name '*.json' | wc -l)"
