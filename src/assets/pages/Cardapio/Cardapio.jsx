import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import styles from "../../../styles/Cardapio.module.css";

export default function Cardapio() {
    const navigate = useNavigate();
    const [user, setUser] = useState(null);
    const [produtos, setProdutos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [erro, setErro] = useState('');
    const [sucesso, setSucesso] = useState('');
    const [editando, setEditando] = useState(null); // produto sendo editado
    const [formEdicao, setFormEdicao] = useState({});

    useEffect(() => {
        const usuarioStr = localStorage.getItem("usuario");
        if (usuarioStr) setUser(JSON.parse(usuarioStr));
        buscarProdutos();
    }, []);

    const buscarProdutos = async () => {
        try {
            const res = await fetch('http://127.0.0.1:5000/produtos', {
                credentials: 'include'
            });
            const data = await res.json();
            setProdutos(data);
        } catch {
            setErro('Erro ao carregar produtos.');
        } finally {
            setLoading(false);
        }
    };

    const excluir = async (id) => {
        if (!window.confirm('Tem certeza que deseja excluir este produto?')) return;
        try {
            const res = await fetch(`http://127.0.0.1:5000/produto/${id}`, {
                method: 'DELETE',
                credentials: 'include'
            });
            const data = await res.json();
            if (res.ok) {
                setSucesso('Produto excluído com sucesso!');
                setProdutos(prev => prev.filter(p => p.id !== id));
                setTimeout(() => setSucesso(''), 3000);
            } else {
                setErro(data.erro || 'Erro ao excluir.');
                setTimeout(() => setErro(''), 3000);
            }
        } catch {
            setErro('Erro de conexão.');
            setTimeout(() => setErro(''), 3000);
        }
    };

    const abrirEdicao = (produto) => {
        setEditando(produto.id);
        setFormEdicao({
            nome: produto.nome,
            descricao: produto.descricao,
            preco: produto.preco,
            categoria: produto.categoria,
            disponivel: produto.disponivel
        });
    };

    const salvarEdicao = async (id) => {
        try {
            const res = await fetch(`http://127.0.0.1:5000/produto/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(formEdicao)
            });
            const data = await res.json();
            if (res.ok) {
                setSucesso('Produto atualizado!');
                setEditando(null);
                buscarProdutos();
                setTimeout(() => setSucesso(''), 3000);
            } else {
                setErro(data.erro || 'Erro ao editar.');
                setTimeout(() => setErro(''), 3000);
            }
        } catch {
            setErro('Erro de conexão.');
            setTimeout(() => setErro(''), 3000);
        }
    };

    // Agrupa por categoria
    const categorias = [...new Set(produtos.map(p => p.categoria))];

    return (
        <div className={styles.pageContainer}>
            <div className={styles.header}>
                <h1 className={styles.title}>Cardápio</h1>
            </div>

            {erro && (
                <div className={styles.toast + ' ' + styles.toastErro}>
                    <span>✕</span><span>{erro}</span>
                </div>
            )}
            {sucesso && (
                <div className={styles.toast + ' ' + styles.toastSucesso}>
                    <span>✓</span><span>{sucesso}</span>
                </div>
            )}

            {loading && <p className={styles.loadingText}>Carregando cardápio...</p>}

            {!loading && categorias.map(categoria => (
                <div key={categoria} className={styles.categoriaSection}>
                    <h2 className={styles.categoriaTitulo}>{categoria}</h2>
                    <div className={styles.cardsGrid}>
                        {produtos
                            .filter(p => p.categoria === categoria)
                            .map(produto => (
                                <div key={produto.id} className={`${styles.card} ${!produto.disponivel ? styles.cardIndisponivel : ''}`}>

                                    {/* Modo edição */}
                                    {editando === produto.id ? (
                                        <div className={styles.formEdicao}>
                                            <input
                                                className={styles.inputEdicao}
                                                value={formEdicao.nome}
                                                onChange={e => setFormEdicao({...formEdicao, nome: e.target.value})}
                                                placeholder="Nome"
                                            />
                                            <textarea
                                                className={styles.inputEdicao}
                                                value={formEdicao.descricao}
                                                onChange={e => setFormEdicao({...formEdicao, descricao: e.target.value})}
                                                placeholder="Descrição"
                                                rows={2}
                                            />
                                            <input
                                                className={styles.inputEdicao}
                                                type="number"
                                                step="0.01"
                                                value={formEdicao.preco}
                                                onChange={e => setFormEdicao({...formEdicao, preco: e.target.value})}
                                                placeholder="Preço"
                                            />
                                            <input
                                                className={styles.inputEdicao}
                                                value={formEdicao.categoria}
                                                onChange={e => setFormEdicao({...formEdicao, categoria: e.target.value})}
                                                placeholder="Categoria"
                                            />
                                            <label className={styles.checkboxLabel}>
                                                <input
                                                    type="checkbox"
                                                    checked={formEdicao.disponivel}
                                                    onChange={e => setFormEdicao({...formEdicao, disponivel: e.target.checked})}
                                                />
                                                Disponível
                                            </label>
                                            <div className={styles.botoesEdicao}>
                                                <button className={styles.btnSalvar} onClick={() => salvarEdicao(produto.id)}>Salvar</button>
                                                <button className={styles.btnCancelar} onClick={() => setEditando(null)}>Cancelar</button>
                                            </div>
                                        </div>
                                    ) : (
                                        <>
                                            <div className={styles.cardTop}>
                                                <h3 className={styles.cardNome}>{produto.nome}</h3>
                                                {!produto.disponivel && (
                                                    <span className={styles.badgeIndisponivel}>Indisponível</span>
                                                )}
                                            </div>
                                            <p className={styles.cardDescricao}>{produto.descricao}</p>
                                            <p className={styles.cardPreco}>
                                                R$ {Number(produto.preco).toFixed(2).replace('.', ',')}
                                            </p>

                                            {/* Botões só para ADM */}
                                            {user?.id_tipo === 1 && (
                                                <div className={styles.botoesAdmin}>
                                                    <button
                                                        className={styles.btnEditar}
                                                        onClick={() => abrirEdicao(produto)}
                                                    >
                                                        ✏️ Editar
                                                    </button>
                                                    <button
                                                        className={styles.btnExcluir}
                                                        onClick={() => excluir(produto.id)}
                                                    >
                                                        🗑️ Excluir
                                                    </button>
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                            ))}
                    </div>
                </div>
            ))}

            {!loading && produtos.length === 0 && (
                <p className={styles.emptyText}>Nenhum produto cadastrado ainda.</p>
            )}
        </div>
    );
}