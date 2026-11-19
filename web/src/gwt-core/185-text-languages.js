
  /* ============================================================ other languages
   * groundwater/text.py, "Other languages" (PLAN.md step 9.2). English is
   * the working language and GWT.data.text is the English. A translation is
   * a folder beside the English files named for the language
   * (src/groundwater/data/text/kri), which the build emits here as
   * GWT.data.translations[code] = {language, text}: the facts of its
   * language.yaml, and as many entries of each file as are translated.
   *
   * The rules are text.py's, rule for rule, and the parity suite holds the
   * two to each other on translations made up for the purpose: an entry not
   * translated (left out, or named and left empty) is said in English and
   * counted; a translation is offered only if it says what it is, who
   * translated it and who checked it, and has no entry English lacks, no
   * sentence that takes other values than the English one, no table row
   * English lacks and nothing blank. Only what a community
   * reads is said through a speaker; reports and notes to whoever builds a
   * document stay in English. */

  /** @typedef {{code: string, language: Rec, fellBack: string[],
   *   phrase: function(string, Record<string, *>=): string,
   *   phraseTable: function(string): Record<string, *>}} Speaker */

  var LANGUAGE_FACTS = ['name', 'translated_by', 'checked_by'];
  var LANGUAGE_CODE = /^[a-z]{2,8}$/;

  /** Every translation the build carries, by language code.
   * @returns {Record<string, Rec>} */
  function translations() {
    return (GWT.data || {}).translations || {};
  }

  /** Each value a template takes, with the formats it writes it in; null
   * where the template does not parse (a lone brace).
   * @param {string} template
   * @returns {Record<string, Record<string, boolean>>|null} */
  function textPlaceholders(template) {
    /** @type {Record<string, Record<string, boolean>>} */
    var taken = {};
    var broken = false;
    TEXT_TOKEN.lastIndex = 0;
    template.replace(TEXT_TOKEN, function (token, name, spec) {
      if (token === '{{' || token === '}}') return token;
      if (name === undefined) { broken = true; return token; }
      /* the two words of a plural are the translation's own to choose */
      var format = spec === undefined ? '' : (spec.indexOf('plural:') === 0 ? 'plural' : spec);
      if (!own(taken, name)) taken[name] = {};
      taken[name][format] = true;
      return token;
    });
    return broken ? null : taken;
  }

  /** Whether a translated sentence takes the values the English one takes,
   * each in a format the English writes it in.
   * @param {Record<string, Record<string, boolean>>} mine
   * @param {Record<string, Record<string, boolean>>} theirs
   * @returns {boolean} */
  function sameValues(mine, theirs) {
    return Object.keys(mine).sort().join('\n') === Object.keys(theirs).sort().join('\n') &&
      Object.keys(mine).every(function (name) {
        return Object.keys(mine[name]).every(function (format) {
          return own(theirs[name], format);
        });
      });
  }

  /** @param {*} value */
  function isPlainObject(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  /** Every reason the translation cannot be offered, in words; an empty
   * list where it can (text.py translation_problems).
   * @param {string} code
   * @param {Record<string, Rec>} [held] the translations to read
   * @param {Record<string, Rec>} [english] the catalogue they translate
   * @returns {string[]} */
  function translationProblems(code, held, english) {
    var all = held || translations();
    var source = english || (GWT.data || {}).text || {};
    if (!own(all, code)) return ['there is no translation ' + pyRepr(code)];
    var entry = all[code];
    var facts = entry.language || {};
    /** @type {string[]} */
    var problems = LANGUAGE_CODE.test(code) ? []
      : [pyRepr(code) + " is not a language's code (two to eight small letters)"];
    LANGUAGE_FACTS.forEach(function (fact) {
      if (!(isPlainObject(facts) && typeof facts[fact] === 'string' && facts[fact].trim())) {
        problems.push('language.yaml does not say ' + fact);
      }
    });
    Object.keys(entry.text || {}).sort().forEach(function (namespace) {
      var entries = entry.text[namespace];
      if (!own(source, namespace)) {
        problems.push(namespace + '.yaml translates a file English does not have');
        return;
      }
      /* a file with nothing in it yet */
      if (entries === null) return;
      if (!isPlainObject(entries)) {
        problems.push(namespace + '.yaml is not a list of entries');
        return;
      }
      Object.keys(entries).sort().forEach(function (key) {
        var ident = namespace + '.' + key, value = entries[key];
        var from = own(source[namespace], key) ? source[namespace][key] : null;
        if (from === null) {
          problems.push(ident + ' is not an entry of the English');
        } else if (value === null) {
          /* named and left empty: not translated yet */
        } else if (isPlainObject(from)) {
          if (!isPlainObject(value)) {
            problems.push(ident + ' is a table in English and a sentence here');
            return;
          }
          Object.keys(value).sort().forEach(function (row) {
            if (!own(from, row)) {
              problems.push(ident + '[' + row + '] is not a row of the English table');
            } else if (value[row] === null) {
              /* not translated yet */
            } else if (typeof value[row] !== 'string' || value[row].indexOf('{') >= 0 ||
                value[row].indexOf('}') >= 0) {
              problems.push(ident + '[' + row + '] is not plain text');
            } else if (!value[row].trim()) {
              problems.push(ident + '[' + row + '] is blank');
            }
          });
        } else if (typeof value !== 'string') {
          problems.push(ident + ' is a sentence in English and not one here');
        } else if (!value.trim()) {
          problems.push(ident + ' is blank');
        } else {
          var mine = textPlaceholders(value), theirs = textPlaceholders(from);
          if (mine === null) {
            problems.push(ident + ' has a lone brace');
          } else if (theirs !== null && !sameValues(mine, theirs)) {
            problems.push(ident + ' does not take the values the English takes (' +
              (Object.keys(theirs).sort().join(', ') || 'none') + '), each in a format it uses');
          }
        }
      });
    });
    return problems;
  }

  /** The translations that can be offered, as {code, name, translated_by,
   * checked_by}, by name: those with no problem (text.py languages).
   * @param {Record<string, Rec>} [held]
   * @param {Record<string, Rec>} [english]
   * @returns {Rec[]} */
  function textLanguages(held, english) {
    var all = held || translations();
    /** @type {Rec[]} */
    var offered = [];
    Object.keys(all).sort().forEach(function (code) {
      if (translationProblems(code, all, english).length) return;
      /** @type {Rec} */
      var language = { code: code };
      LANGUAGE_FACTS.forEach(function (fact) { language[fact] = all[code].language[fact].trim(); });
      offered.push(language);
    });
    return offered.sort(function (a, b) {
      return a.name < b.name ? -1 : (a.name > b.name ? 1
        : (a.code < b.code ? -1 : (a.code > b.code ? 1 : 0)));
    });
  }

  /** The catalogue in one language, with English where it has no words
   * (text.py Speaker). speaker('') is English. A language that cannot be
   * offered is refused with its reasons. fellBack holds the entries it had
   * to say in English, each once, in the order they were first asked for.
   * @param {string} [code]
   * @param {Record<string, Rec>} [held]
   * @param {Record<string, Rec>} [english]
   * @returns {Speaker} */
  function speaker(code, held, english) {
    var lang = code || '';
    var source = english || (GWT.data || {}).text || {};
    /** @type {Record<string, Rec>} */
    var text = {};
    /** @type {Rec} */
    var language = {};
    /** @type {string[]} */
    var fellBack = [];
    if (lang) {
      var all = held || translations();
      var problems = translationProblems(lang, all, source);
      if (problems.length) {
        throw new Error('text: the translation ' + pyRepr(lang) + ' cannot be used: ' +
          problems.join('; '));
      }
      text = all[lang].text || {};
      language = { code: lang };
      LANGUAGE_FACTS.forEach(function (fact) { language[fact] = all[lang].language[fact].trim(); });
    }
    /** @param {string} id */
    function sourceOf(id) {
      var dot = id.indexOf('.');
      var namespace = id.slice(0, dot), key = id.slice(dot + 1);
      if (dot < 0 || !own(source, namespace) || !own(source[namespace], key)) {
        throw new Error('text: no entry ' + pyRepr(id) + ' in data/text');
      }
      return { namespace: namespace, key: key, from: source[namespace][key] };
    }
    /** @param {string} id */
    function missed(id) {
      if (lang && fellBack.indexOf(id) < 0) fellBack.push(id);
    }
    return {
      code: lang, language: language, fellBack: fellBack,
      phrase: function (id, values) {
        var at = sourceOf(id);
        if (typeof at.from !== 'string') {
          throw new TypeError('text: ' + pyRepr(id) + ' is a table; read it with phraseTable');
        }
        var file = (own(text, at.namespace) && text[at.namespace]) || {};
        var mine = own(file, at.key) ? file[at.key] : null;
        if (mine === null) missed(id);
        return renderText(mine === null ? at.from : mine, values);
      },
      phraseTable: function (id) {
        var at = sourceOf(id);
        if (!isPlainObject(at.from)) {
          throw new TypeError('text: ' + pyRepr(id) + ' is a sentence; read it with phrase');
        }
        var file = (own(text, at.namespace) && text[at.namespace]) || {};
        var mine = own(file, at.key) && file[at.key] ? file[at.key] : {};
        /** @type {Record<string, *>} */
        var table = {};
        var short = false;
        Object.keys(at.from).forEach(function (row) {
          if (own(mine, row) && mine[row] !== null) table[row] = mine[row];
          else { table[row] = at.from[row]; short = true; }
        });
        if (short) missed(id);
        return table;
      },
    };
  }

  Object.assign(C, {
    translations: translations, translationProblems: translationProblems,
    textLanguages: textLanguages, speaker: speaker,
  });
